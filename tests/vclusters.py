# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Check independent virtual clusters, access, and instance removal."""

from copy import deepcopy
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import yaml

from helpers import load_helpers
from render import arguments, environment, manifest, render

NAMING = load_helpers("_resource_name", "_vcluster_profile")
resource_name = NAMING["_resource_name"]
profile_name = NAMING["_vcluster_profile"]


def user_roles(resources):
    return {
        ref["name"]
        for ref in resources["keycloak-roles-user-s-joe"]["spec"]["forProvider"]["roleIdsRefs"]
    }


def configuration(resources, instance):
    secret = manifest(resources, resource_name("vcluster", "s-joe", instance, "config"))
    assert "stringData" not in secret
    return json.loads(base64.b64decode(secret["data"]["config.yaml"]))


def connections(resources):
    return [c for c in resources["composite"]["status"]["connections"] if c["type"] == "vcluster"]


def check_volume_bindings(args, env, source, baseline):
    bound_source = deepcopy(source)
    binding = {"name": "analysis", "target": {"namespace": "demo", "name": "analysis"}}
    bound_source["spec"]["vclusters"]["vc0"]["volumeBindings"] = [binding]

    def keys(target):
        target_id = hashlib.sha256(json.dumps(target, sort_keys=True).encode()).hexdigest()[:10]
        suffix = "volume-binding-analysis-" + target_id
        return {
            ending: resource_name("vcluster", "s-joe", "vc0", *(["access"] if virtual else []), suffix + ending)
            for ending, virtual in (("-pv", True), ("-pvc", True), ("-claim-policy", True),
                                    ("-claim-policy-binding", True), ("-mount-policy", False),
                                    ("-mount-policy-binding", False))
        }

    binding_keys = keys(binding["target"])
    bootstrap = render(args, env, bound_source, [], include_composite=True)
    assert binding_keys["-pv"] not in bootstrap and binding_keys["-pvc"] not in bootstrap
    anchor_observation = deepcopy(bootstrap[binding_keys["-claim-policy"]])
    anchor_observation["status"] = {"atProvider": {"manifest": {"metadata": {"uid": "test-policy-uid"}}}}
    rendered = render(args, env, bound_source, [anchor_observation], include_composite=True)
    pvc_key = binding_keys["-pvc"]
    pv = manifest(rendered, binding_keys["-pv"])
    pvc = manifest(rendered, pvc_key)
    assert pvc["metadata"]["namespace"] == "demo" and pvc["metadata"]["name"] == "analysis"
    assert pvc["metadata"]["labels"]["vcluster.loft.sh/controlled-by"] == "datalab-volume"
    assert pv["metadata"]["labels"] == pvc["metadata"]["labels"]
    assert pvc["spec"]["volumeName"] == pv["metadata"]["name"]
    assert pvc["spec"]["storageClassName"] == pv["spec"]["storageClassName"] == ""
    assert pvc["spec"]["resources"]["requests"]["storage"] == pv["spec"]["capacity"]["storage"] == "2Gi"
    assert pv["spec"]["persistentVolumeReclaimPolicy"] == "Retain"
    anchor = manifest(rendered, binding_keys["-claim-policy"])
    owner = {"apiVersion": "admissionregistration.k8s.io/v1", "kind": "ValidatingAdmissionPolicy",
             "name": anchor["metadata"]["name"], "uid": "test-policy-uid", "controller": True, "blockOwnerDeletion": False}
    for ending in ("-pv", "-pvc"):
        assert rendered[binding_keys[ending]]["spec"]["managementPolicies"] == ["Observe"]
        assert manifest(rendered, binding_keys[ending])["metadata"]["ownerReferences"] == [owner]
    assert rendered[binding_keys["-claim-policy"]]["spec"]["forProvider"]["deletionPropagationPolicy"] == "Background"
    controller_args = configuration(rendered, "vc0")["controlPlane"]["distro"]["k8s"]["controllerManager"]["extraArgs"]
    controllers = next(value.removeprefix("--controllers=").split(",") for value in controller_args if value.startswith("--controllers="))
    assert "*" in controllers and "-persistentvolume-binder" not in controllers
    assert "-attachdetach" in controllers and "-persistentvolume-expander" in controllers
    assert configuration(rendered, "vc1")["controlPlane"]["distro"]["k8s"]["controllerManager"]["extraArgs"] == controller_args
    assert configuration(baseline, "vc0")["controlPlane"]["distro"]["k8s"]["controllerManager"]["extraArgs"] == controller_args
    assert pv["spec"]["claimRef"] == {"namespace": "demo", "name": "analysis", "uid": ""}
    readiness = rendered[pvc_key]["spec"]["readiness"]
    assert readiness["policy"] == "DeriveFromCelQuery" and "Bound" in readiness["celQuery"]

    host_keys = {key for key in baseline if key.startswith("volume-")}
    for key in host_keys:
        assert rendered[key]["spec"] == baseline[key]["spec"]
        assert "vcluster.loft.sh/managed-by" not in manifest(rendered, key).get("metadata", {}).get("labels", {})
    host_guard = resource_name("volume", "s-joe", "analysis", "claim-policy")
    host_guard_binding = resource_name("volume", "s-joe", "analysis", "claim-policy-binding")
    protection = [binding_keys["-mount-policy"], binding_keys["-mount-policy-binding"], host_guard, host_guard_binding]
    dependencies = {reference["dependsOn"]["name"] for reference in rendered[pvc_key]["spec"]["references"] if "dependsOn" in reference}
    assert dependencies == {*protection, binding_keys["-claim-policy"], binding_keys["-claim-policy-binding"], binding_keys["-pv"]}
    assert all(reference["dependsOn"]["namespace"] == "workspace"
               for reference in rendered[pvc_key]["spec"]["references"] if "dependsOn" in reference)
    control = resource_name("vcluster", "s-joe", "vc0", "statefulset")
    assert manifest(rendered, control)["spec"]["replicas"] == 0
    assert manifest(rendered, resource_name("vcluster", "s-joe", "vc1", "statefulset"))["spec"]["replicas"] == 1
    assert rendered[control]["spec"].get("references", []) == baseline[control]["spec"].get("references", [])

    observed = [anchor_observation]
    for key in protection:
        ready = deepcopy(rendered[key])
        ready["status"] = {"conditions": [{"type": "Ready", "status": "True"}]}
        observed.append(ready)
    released = render(args, env, bound_source, observed)
    assert manifest(released, control)["spec"]["replicas"] == 1
    deleting_policy = deepcopy(observed)
    deleting_policy[1]["metadata"]["deletionTimestamp"] = "2026-11-23T01:00:00Z"
    blocked = render(args, env, bound_source, deleting_policy)
    assert manifest(blocked, control)["spec"]["replicas"] == 0
    native = deepcopy(pvc)
    pvc_observation = deepcopy(rendered[pvc_key])
    for uid, deleting, expected in (("old-claim", False, "old-claim"),
                                    ("old-claim", True, ""), ("new-claim", False, "new-claim")):
        native["metadata"]["uid"] = uid
        native["metadata"].pop("deletionTimestamp", None)
        if deleting:
            native["metadata"]["deletionTimestamp"] = "2026-11-21T01:00:00Z"
        pvc_observation["status"] = {"atProvider": {"manifest": deepcopy(native)}}
        rebound = render(args, env, bound_source, [*observed, pvc_observation])
        assert manifest(rebound, binding_keys["-pv"])["spec"]["claimRef"]["uid"] == expected
    print("PASS volume bindings wait for protection and rebind after PVC replacement")

    retargeted = deepcopy(bound_source)
    retargeted["spec"]["vclusters"]["vc0"]["volumeBindings"][0]["target"]["namespace"] = "reports"
    moved = render(args, env, retargeted, observed)
    moved_keys = keys(retargeted["spec"]["vclusters"]["vc0"]["volumeBindings"][0]["target"])
    moved_anchor = deepcopy(moved[moved_keys["-claim-policy"]])
    moved_anchor["status"] = {"atProvider": {"manifest": {"metadata": {"uid": "test-moved-policy-uid"}}}}
    ready_control = deepcopy(released[control])
    ready_control["status"] = {"conditions": [{"type": "Ready", "status": "True"}]}
    moved_protection = []
    for ending in ("-mount-policy", "-mount-policy-binding"):
        ready = deepcopy(moved[moved_keys[ending]])
        ready["status"] = {"conditions": [{"type": "Ready", "status": "True"}]}
        moved_protection.append(ready)
    moved = render(args, env, retargeted, [*observed, moved_anchor, ready_control, *moved_protection])
    assert not set(binding_keys.values()) & set(moved)
    for ending in binding_keys:
        old = manifest(rendered, binding_keys[ending])["metadata"]
        new = manifest(moved, moved_keys[ending])["metadata"]
        assert (old.get("namespace"), old["name"]) != (new.get("namespace"), new["name"])
    check_binding_admission(rendered, binding_keys, host_guard)
    check_mount_scope(manifest(moved, moved_keys["-mount-policy"]), "reports",
                      "analysis-x-reports-x-vcluster-vc0")
    records = [rendered[binding_keys[ending]] for ending in ("-pv", "-pvc")]
    ready_control = deepcopy(released[control])
    ready_control["status"] = {"conditions": [{"type": "Ready", "status": "True"}]}
    cleaned = render(args, env, source, [ready_control, *records])
    assert not set(binding_keys.values()) & set(cleaned)
    removed = deepcopy(bound_source)
    removed["spec"]["vclusters"].pop("vc0")
    without_instance = render(args, env, removed, records)
    for key in host_keys:
        assert without_instance[key]["spec"] == baseline[key]["spec"]
    assert not set(binding_keys.values()) & set(without_instance)
    assert not set(binding_keys.values()) & set(baseline)
    print("PASS binding changes preserve host volumes and backups")

    invalid = deepcopy(bound_source)
    invalid["spec"]["vclusters"]["vc0"]["volumeBindings"][0]["name"] = "missing"
    render(args, env, invalid, [], error="Each volume binding must select a declared named volume")
    invalid = deepcopy(bound_source)
    invalid["spec"]["vclusters"]["vc1"]["volumeBindings"] = [binding]
    render(args, env, invalid, [], error="A named volume can have one virtual binding")
    invalid = deepcopy(bound_source)
    invalid["spec"]["volumes"]["other"] = {}
    invalid["spec"]["vclusters"]["vc0"]["volumeBindings"].append({"name": "other", "target": binding["target"]})
    render(args, env, invalid, [], error="target PVCs must be unique")
    print("PASS undeclared volumes and conflicting virtual bindings fail")


def admission_case(name, policy, values, allowed):
    return {"Name": name, "Matches": [item["expression"] for item in policy["spec"]["matchConditions"]],
            "Validations": [item["expression"] for item in policy["spec"]["validations"]],
            "Values": deepcopy(values), "Allowed": allowed}


def run_admission(tests):
    subprocess.run(["go", "run", "."], cwd=Path(__file__).parent / "admission",
                   input=json.dumps(tests), text=True, check=True, timeout=180)


def check_mount_scope(policy, namespace, translated):
    # A deny rule makes the mutation's match conditions observable in the CEL runner.
    scope = deepcopy(policy)
    scope["spec"]["validations"] = [{"expression": "false"}]
    values = {"request": {"userInfo": {"username": "system:serviceaccount:s-joe:vc-vcluster-vc0"}},
              "object": {"metadata": {"annotations": {"vcluster.loft.sh/object-namespace": namespace}},
                         "spec": {"volumes": [{"name": "data", "persistentVolumeClaim": {"claimName": translated}}]}},
              "oldObject": {}, "params": {}}
    cases = [admission_case("only this translated claim matches the mount policy", scope, values, False)]
    for name, change in (
            ("another virtual cluster", lambda value: value["request"]["userInfo"].update(username="system:serviceaccount:s-joe:vc-vcluster-vc1")),
            ("another virtual namespace", lambda value: value["object"]["metadata"]["annotations"].update({"vcluster.loft.sh/object-namespace": "other"})),
            ("another translated claim", lambda value: value["object"]["spec"]["volumes"][0]["persistentVolumeClaim"].update(claimName="other")),
            ("Pod without volumes", lambda value: value["object"]["spec"].pop("volumes")),
            ("Pod without namespace annotation", lambda value: value["object"]["metadata"].pop("annotations"))):
        changed = deepcopy(values)
        change(changed)
        cases.append(admission_case(name + " is outside the mount policy", scope, changed, True))
    run_admission(cases)


def check_binding_admission(resources, keys, host_guard):
    host = manifest(resources, host_guard)
    virtual = manifest(resources, keys["-claim-policy"])
    values = {"request": {"operation": "CREATE", "namespace": "s-joe", "userInfo": {
        "username": "system:serviceaccount:s-joe:vc-vcluster-vc0"}},
        "object": {"metadata": {"name": "volume-analysis"}}, "oldObject": None, "params": {}}
    tests = []
    for operation in ("CREATE", "UPDATE", "DELETE"):
        changed = deepcopy(values)
        changed["request"]["operation"] = operation
        if operation == "DELETE":
            changed["object"], changed["oldObject"] = None, changed["object"]
        tests.append(admission_case("syncer cannot " + operation + " a host volume", host, changed, False))
    for name, change in (
            ("other host claim", lambda value: value["object"]["metadata"].update(name="application-data")),
            ("operator identity", lambda value: value["request"]["userInfo"].update(username="system:serviceaccount:crossplane-system:provider-kubernetes")),
            ("other workspace syncer", lambda value: value["request"]["userInfo"].update(username="system:serviceaccount:other:vc-vcluster-vc0"))):
        changed = deepcopy(values)
        change(changed)
        tests.append(admission_case(name + " is outside host protection", host, changed, True))
    values["request"].update(namespace="demo", operation="UPDATE")
    values["object"] = deepcopy(manifest(resources, keys["-pvc"]))
    values["object"]["metadata"]["ownerReferences"][0]["uid"] = "test-policy-uid"
    values["oldObject"] = deepcopy(values["object"])
    tests.append(admission_case("valid virtual claim binding", virtual, values, True))
    creation = deepcopy(values)
    creation["request"]["operation"] = "CREATE"
    creation["oldObject"] = None
    tests.append(admission_case("new virtual claim has a valid GC owner", virtual, creation, True))
    creation["object"]["metadata"]["ownerReferences"][0]["uid"] = ""
    tests.append(admission_case("claim without an owner UID is denied", virtual, creation, False))
    for name, change in (
            ("removed sync marker", lambda value: value["object"]["metadata"].pop("labels")),
            ("changed sync marker", lambda value: value["object"]["metadata"]["labels"].update({"vcluster.loft.sh/controlled-by": "other"})),
            ("changed volume", lambda value: value["object"]["spec"].update(volumeName="other")),
            ("dynamic storage class", lambda value: value["object"]["spec"].update(storageClassName="standard")),
            ("removed GC owner", lambda value: value["object"]["metadata"].pop("ownerReferences")),
            ("changed GC owner", lambda value: value["object"]["metadata"]["ownerReferences"][0].update(uid="other-policy-uid")),
            ("additional GC owner", lambda value: value["object"]["metadata"]["ownerReferences"].append({"apiVersion": "v1", "kind": "Namespace", "name": "demo", "uid": "other-owner"}))):
        changed = deepcopy(values)
        change(changed)
        tests.append(admission_case(name + " is denied", virtual, changed, False))
    values["object"]["metadata"]["name"] = "application-data"
    tests.append(admission_case("ordinary virtual PVCs are outside binding protection", virtual, values, True))
    assert virtual["spec"]["matchConstraints"]["resourceRules"][0]["operations"] == ["CREATE", "UPDATE"]
    assert host["spec"]["matchConstraints"]["namespaceSelector"]["matchLabels"] == {"kubernetes.io/metadata.name": "s-joe"}
    run_admission(tests)
    check_mount_scope(manifest(resources, keys["-mount-policy"]), "demo", "analysis-x-demo-x-vcluster-vc0")


def check_instance_isolation(resources):
    assert "namespace-s-joe" in resources
    for instance in ("vc0", "vc1"):

        def key(suffix):
            return resource_name("vcluster", "s-joe", instance, suffix)

        runtime = f"vcluster-{instance}"
        statefulset = manifest(resources, key("statefulset"))
        assert statefulset["metadata"]["namespace"] == "s-joe"
        assert statefulset["metadata"]["name"] == runtime
        assert (
            statefulset["spec"]["template"]["metadata"]["labels"]
            == statefulset["spec"]["selector"]["matchLabels"]
        )
        assert (
            statefulset["spec"]["template"]["spec"]["serviceAccountName"]
            == f"vc-{runtime}"
        )
        assert (
            manifest(resources, key("service"))["spec"]["selector"]
            == statefulset["spec"]["selector"]["matchLabels"]
        )
        route = manifest(resources, key("route"))["spec"]["rules"][0]
        assert route["matches"][0]["path"]["value"] == f"/.{instance}"
        assert route["backendRefs"][0]["name"] == runtime
        assert route["filters"][0]["urlRewrite"]["path"]["replacePrefixMatch"] == "/"
        tls = manifest(resources, key("backend-tls"))["spec"]
        assert tls["targetRefs"][0]["name"] == runtime
        assert tls["validation"]["hostname"] == f"{runtime}.s-joe.svc"
        authentication = json.loads(
            manifest(resources, key("authentication"))["data"]["authentication.json"]
        )
        assert (
            f"vcluster_{instance}_demo"
            in authentication["jwt"][0]["claimValidationRules"][0]["expression"]
        )
        other = "vc1" if instance == "vc0" else "vc0"
        assert (
            f"vcluster_{other}_demo"
            not in authentication["jwt"][0]["claimValidationRules"][0]["expression"]
        )
        assert configuration(resources, instance)["experimental"]["deploy"]["vcluster"]["manifests"] == ""
    print("PASS virtual clusters have separate routes and roles")


def check_membership(args, env, source, resources):
    observed = []
    implicit = deepcopy(source)
    implicit["spec"]["users"] = ["joe", "jane"]
    implicit["spec"]["vclusters"] = {"vc0": {}, "vc1": {"groups": []}}
    automatic = render(args, env, implicit, observed, include_composite=True)
    assert automatic["keycloak-memberships-users-s-joe"]["spec"]["forProvider"]["members"] == ["joe", "jane"]
    assert user_roles(automatic) == {
        "s-joe-ws-access", "s-joe-ws-api",
    }
    assert {
        ref["name"] for ref in automatic["keycloak-roles-admin-s-joe-admin"]["spec"]["forProvider"]["roleIdsRefs"]
    } == {
        "s-joe-ws-admin", "s-joe-ws-api",
        *(profile_name("s-joe", instance, "cluster-admin") for instance in ("vc0", "vc1")),
    }
    assert all(
        ref["policy"]["resolve"] == "Always"
        for ref in automatic["keycloak-roles-user-s-joe"]["spec"]["forProvider"]["roleIdsRefs"]
    )
    for instance in ("vc0", "vc1"):
        profile = profile_name("s-joe", instance, "cluster-admin")
        assert automatic[f"keycloak-vcluster-role-{profile}"]["spec"]["forProvider"]["name"] == f"vcluster_{instance}_cluster-admin"
        bindings = [
            body["spec"]["forProvider"]["manifest"]
            for body in automatic.values()
            if body.get("kind") == "Object"
            and body["metadata"].get("labels", {}).get("datalabs.versioneer.at/vcluster") == instance
            and body["spec"]["forProvider"].get("manifest", {}).get("kind") == "ClusterRoleBinding"
        ]
        assert len(bindings) == 1
        assert bindings[0]["roleRef"]["name"] == "cluster-admin"
        assert bindings[0]["subjects"] == [{"apiGroup": "rbac.authorization.k8s.io", "kind": "Group", "name": f"datalab:s-joe:vcluster_{instance}_cluster-admin"}]
        assert any(
            c["type"] == "vcluster" and c["instance"] == instance and c["group"] == "cluster-admin"
            for c in automatic["composite"]["status"]["connections"]
        )
    explicit = deepcopy(implicit)
    explicit["spec"]["vclusters"]["vc0"]["groups"] = [
        {"name": "cluster-admin", "namespace": "*", "role": "cluster-admin"}
    ]
    repeated = render(args, env, explicit, observed, include_composite=True)
    bindings = [manifest(repeated, key) for key, body in repeated.items()
                if body.get("kind") == "Object"
                and body["metadata"].get("labels", {}).get("datalabs.versioneer.at/vcluster") == "vc0"
                and manifest(repeated, key).get("kind") == "ClusterRoleBinding"]
    assert len(bindings) == 1 and bindings[0]["roleRef"]["name"] == "cluster-admin"
    profiles = [c for c in repeated["composite"]["status"]["connections"]
                if c["type"] == "vcluster" and c["instance"] == "vc0" and c["group"] == "cluster-admin"]
    assert len(profiles) == 1
    implicit["spec"]["users"].remove("jane")
    implicit["spec"]["vclusters"] = {}
    implicit["spec"]["volumes"] = {}
    disabled = render(args, env, implicit, observed)
    assert user_roles(disabled) == {"s-joe-ws-access", "s-joe-ws-api"}
    assert disabled["keycloak-memberships-users-s-joe"]["spec"]["forProvider"]["members"] == ["joe"]
    assert not any(key.startswith("keycloak-vcluster-") for key in disabled)
    assert disabled["keycloak-service-account-role-api-s-joe-ws-api"]["spec"] == automatic["keycloak-service-account-role-api-s-joe-ws-api"]["spec"]
    vacant_source = deepcopy(source)
    vacant_source["spec"]["users"] = []
    vacant = render(args, env, vacant_source, observed)
    assert "keycloak-memberships-users-s-joe" not in vacant
    assert "keycloak-memberships-admins-s-joe-admin" not in vacant
    assert user_roles(vacant) == user_roles(resources)
    assert manifest(vacant, resource_name("vcluster", "s-joe", "vc0", "statefulset")) == manifest(resources, resource_name("vcluster", "s-joe", "vc0", "statefulset"))
    print("PASS only administrators receive built-in administration; removal clears managed grants")


def check_secret_bindings(args, env, source):
    observed = []
    bound_source, bound_env = deepcopy(source), deepcopy(env)
    bound_source["spec"]["stores"] = {"pg0": {"type": "postgres", "names": ["analytics"]}}
    bound_env["data"]["customSecrets"] = [
        {"name": "github-development"}, {"name": "missing"}
    ]
    bound_source["spec"]["vclusters"]["vc0"]["secretBindings"] = [
        {"type": kind, "name": name,
         "target": {"namespace": "applications", "name": target}}
        for kind, name, target in (
            ("postgres", "pg0", "database-credentials"),
            ("custom", "github-development", "github-credentials"),
            ("custom", "missing", "missing-credentials"),
            ("custom", "unknown", "unknown-credentials"),
        )
    ]
    custom_key = resource_name(
        "observe-custom-secret", "s-joe", "s-joe", "github-development"
    )
    custom_source = {
        "apiVersion": "kubernetes.m.crossplane.io/v1alpha1", "kind": "Object",
        "metadata": {"name": custom_key, "namespace": "workspace",
                     "annotations": {"crossplane.io/composition-resource-name": custom_key}},
        "status": {
            "conditions": [{"type": "Ready", "status": "True"}],
            "atProvider": {"manifest": {
                "apiVersion": "v1", "kind": "Secret",
                "metadata": {"namespace": "s-joe", "name": "github-development"},
                "data": {"token": base64.b64encode(b"test-token").decode()},
            }},
        },
    }
    pending = render(args, bound_env, bound_source, [*observed, custom_source], include_composite=True)
    custom_ref = next(c["secretRef"] for c in pending["composite"]["status"]["connections"] if c["type"] == "custom")
    copy = next(body for body in pending.values() if body.get("kind") == "Secret"
                and body["metadata"]["name"] == custom_ref["name"])
    bound = render(args, bound_env, bound_source, [*observed, custom_source, copy], include_composite=True)
    published = bound["composite"]["status"]["connections"]
    custom = [c for c in published if c["type"] == "custom"]
    assert custom == [{"name": "github-development", "type": "custom", "ready": True,
                       "secretRef": {"namespace": "workspace", "name": copy["metadata"]["name"]}}]
    assert not next(c for c in published if c["type"] == "postgres")["ready"]

    def native_secrets(rendered, instance):
        return configuration(rendered, instance)["sync"]["fromHost"]["secrets"]

    source_ref = custom[0]["secretRef"]
    assert native_secrets(bound, "vc0") == {
        "enabled": True,
        "mappings": {"byName": {
            f"{source_ref['namespace']}/{source_ref['name']}": "applications/github-credentials"
        }},
    }
    assert native_secrets(bound, "vc1") == {"enabled": False, "mappings": {"byName": {}}}
    unavailable = render(args, bound_env, bound_source, observed, include_composite=True)
    assert not any(c["type"] == "custom" for c in unavailable["composite"]["status"]["connections"])
    assert native_secrets(unavailable, "vc0") == {"enabled": False, "mappings": {"byName": {}}}
    print("PASS only ready connection references generate native Secret mappings")


def check_control_plane_settings(args, env, source, resources):
    observed = []

    def settings(rendered, instance="vc0"):
        control_plane = configuration(rendered, instance)["controlPlane"]
        pod = manifest(rendered, resource_name("vcluster", "s-joe", instance, "statefulset"))["spec"]["template"]
        checksum = pod["metadata"]["annotations"]["datalabs.versioneer.at/configuration-checksum"]
        assert control_plane["statefulSet"]["resources"] == pod["spec"]["containers"][0]["resources"]
        return control_plane, checksum

    defaults, _ = settings(resources)
    tuned_env = deepcopy(env)
    embedded = {
        "enabled": True,
        "dataSource": "sqlite:///data/custom.db",
        "extraArgs": ["--datastore-max-open-connections=2"],
    }
    tuned_env["data"]["vcluster"]["backingStore"] = {"database": {"embedded": embedded}}
    tuned = render(args, tuned_env, source, observed)
    for instance in ("vc0", "vc1"):
        control_plane, checksum = settings(tuned, instance)
        assert control_plane["backingStore"]["database"]["embedded"] == embedded
        assert checksum != settings(resources, instance)[1]
    print("PASS database settings reach both configurations and change the Pod checksum")

    resource_overrides = {
        "requests": {"cpu": "300m", "memory": "2Gi"},
        "limits": {"cpu": "3", "memory": "3Gi"},
    }
    resource_env = deepcopy(tuned_env)
    resource_env["data"]["vcluster"]["resources"] = resource_overrides
    changed = render(args, resource_env, source, observed)
    expected = {
        section: {**defaults["statefulSet"]["resources"][section], **values}
        for section, values in resource_overrides.items()
    }
    for instance in ("vc0", "vc1"):
        control_plane, checksum = settings(changed, instance)
        assert control_plane["statefulSet"]["resources"] == expected
        assert checksum != settings(tuned, instance)[1]
    reordered_env = deepcopy(tuned_env)
    reordered_env["data"]["vcluster"]["backingStore"]["database"]["embedded"] = dict(reversed(list(embedded.items())))
    assert settings(render(args, reordered_env, source, observed)) == settings(tuned)
    print("PASS resource overrides apply to both instances; key order causes no rollout")


def check_public_profiles(args, env, source, resources):
    for instance in ("vc0", "vc1"):
        profile = profile_name("s-joe", instance, "demo")
        scope_resource = resource_name(profile, "scope")
        scope = resources[f"keycloak-optional-scope-{scope_resource}"]["spec"]["forProvider"]
        assert scope["name"] == f"s-joe:vclusters_{instance}_demo"
        mappings = [body["spec"]["forProvider"] for body in resources.values()
                    if body.get("kind") == "RoleMapper"
                    and body["spec"]["forProvider"].get("clientScopeIdRef", {}).get("name") == scope_resource]
        assert len(mappings) == 1 and mappings[0]["roleIdRef"]["name"] == profile
    print("PASS each instance has its own optional profile role scope")

    profiles = connections(resources)
    assert len(profiles) == 4
    assert all(not c["ready"] for c in profiles)
    for connection in profiles:
        secret = resources[resource_name("connection", connection["secretRef"]["name"])]
        assert "stringData" not in secret
        assert set(secret["data"]) == {"kubeconfig", "client-id", "issuer-url"}
        values = {key: base64.b64decode(value).decode() for key, value in secret["data"].items()}
        assert values["client-id"] == "s-joe"
        config = json.loads(values["kubeconfig"])
        assert config["clusters"][0]["cluster"]["server"] == (
            f"https://s-joe.lab.acme.com/.{connection['instance']}"
        )
        namespace = connection["targetNamespace"]
        assert config["contexts"][0]["context"]["namespace"] == (
            "default" if namespace == "*" else namespace
        )
        user = config["users"][0]["user"]
        assert set(user) == {"exec"}
        assert set(user["exec"]) == {"apiVersion", "interactiveMode", "command", "args"}
        if connection["group"] == "cluster-admin":
            assert user["exec"]["interactiveMode"] == "IfAvailable"
            assert user["exec"]["args"][2:] == ["--issuer", values["issuer-url"], "--client-id", "s-joe"]
        else:
            assert user["exec"]["interactiveMode"] == "Never"
            assert user["exec"]["args"][2:] == ["--token-only"]
        assert set(config["clusters"][0]["cluster"]) == {"server"}
    ready_observed = []
    for body in resources.values():
        if body.get("kind") not in ("Secret", "Datalab"):
            body = deepcopy(body)
            body["status"] = {"conditions": [{"type": "Ready", "status": "True"}]}
            ready_observed.append(body)
    ready_resources = render(args, env, source, ready_observed, include_composite=True)
    ready_profiles = connections(ready_resources)
    assert len(ready_profiles) == len(profiles)
    assert all(c["ready"] for c in ready_profiles)
    assert not any("observe-client" in key for key in ready_resources)
    print("PASS public profiles contain no credentials and report runtime readiness")


def check_instance_removal(args, env, source, resources):
    reduced = deepcopy(source)
    del reduced["spec"]["vclusters"]["vc0"]
    reduced_resources = render(args, env, reduced, [])
    assert resource_name("vcluster", "s-joe", "vc0", "statefulset") not in reduced_resources
    assert user_roles(reduced_resources) == {
        "s-joe-ws-access", "s-joe-ws-api", profile_name("s-joe", "vc1", "demo")
    }
    assert manifest(
        reduced_resources, resource_name("vcluster", "s-joe", "vc1", "statefulset")
    ) == manifest(resources, resource_name("vcluster", "s-joe", "vc1", "statefulset"))
    key = resource_name("volume", "s-joe", "analysis")
    assert manifest(reduced_resources, key) == manifest(resources, key)
    provider = resource_name("s-joe", "vcluster", "vc0")
    virtual = {key for key, body in resources.items()
               if body.get("spec", {}).get("providerConfigRef", {}).get("name") == provider}
    paused = []
    for key, original in resources.items():
        if key == "composite":
            continue
        body = deepcopy(original)
        if key in virtual:
            body["metadata"].setdefault("annotations", {})["crossplane.io/paused"] = "true"
        paused.append(body)
    released = render(args, env, reduced, paused)
    for key in virtual:
        assert released[key]["metadata"]["annotations"]["crossplane.io/paused"] == "false"
        assert released[key]["spec"]["managementPolicies"] == ["Observe"]
    removed = render(args, env, reduced, list(released.values()))
    assert not virtual & set(removed)
    virtual_names = {body["metadata"]["name"] for body in paused
                     if body.get("spec", {}).get("providerConfigRef", {}).get("name") == provider}
    assert any(body.get("kind") == "Usage" and body["spec"].get("by", {}).get(
        "resourceRef", {}).get("name") in virtual_names for body in removed.values())
    cleared = render(args, env, reduced, list(removed.values()))
    assert not any(body.get("kind") == "Usage" and body["spec"].get("by", {}).get(
        "resourceRef", {}).get("name") in virtual_names for body in cleared.values())
    print("PASS removed instances release paused records and do not recreate their Usage objects")
    print("PASS removing one instance preserves the other instance and host volumes")


def check_name_collisions(args, env, source):
    group = source["spec"]["vclusters"]["vc0"]["groups"][0]
    hyphenated = deepcopy(source)
    hyphenated["spec"]["vclusters"] = {
        instance: {"groups": [{**group, "name": profile}]}
        for instance, profile in (
            ("vc0", "demo-admin"),
            ("vc0-demo", "admin"),
            ("vc0-workload", "demo"),
            ("vc0-headless", "demo"),
        )
    }
    distinct = render(args, env, hyphenated, [], include_composite=True)
    profiles = connections(distinct)
    assert len({c["name"] for c in profiles}) == 8
    assert len({c["secretRef"]["name"] for c in profiles}) == 8
    host_objects = [
        resource["spec"]["forProvider"]["manifest"]
        for resource in distinct.values()
        if resource.get("kind") == "Object"
        and resource["spec"]["providerConfigRef"]["name"] == "provider-kubernetes"
        and resource["spec"].get("managementPolicies") != ["Observe"]
    ]
    identities = [
        (
            body["apiVersion"],
            body["kind"],
            body["metadata"].get("namespace"),
            body["metadata"]["name"],
        )
        for body in host_objects
    ]
    assert len(set(identities)) == len(
        identities
    ), "Virtual clusters share host objects"
    assert len([body for body in host_objects if body["kind"] == "StatefulSet"]) == 4
    print(
        "PASS hyphenated instance and profile names keep separate host objects and connection references"
    )


def check_placement(args, env, source, baseline):
    native = configuration(baseline, "vc0")
    assert native["sync"]["fromHost"]["nodes"]["enabled"] is False
    assert native["sync"]["fromHost"]["nodes"]["selector"]["labels"] == {}
    assert native["sync"]["toHost"]["pods"]["enforceTolerations"] == []
    assert "nodeSelector" not in manifest(baseline, resource_name("vcluster", "s-joe", "vc0", "statefulset"))["spec"]["template"]["spec"]
    assert manifest(baseline, resource_name("vcluster", "s-joe", "vc0", "statefulset"))["spec"]["replicas"] == 1
    placed_env = deepcopy(env)
    placement = {
        "controlPlane": {"nodeSelector": {"pool": "general"}, "tolerations": [
            {"key": "control", "operator": "Exists", "effect": "NoSchedule"}]},
        "workloads": {"nodeSelector": {"pool": "vcluster"},
                      "enforceTolerations": ["dedicated=vcluster:NoSchedule"]},
    }
    placed_env["data"]["vcluster"]["scheduling"] = placement
    placed = render(args, placed_env, source, [], include_composite=True)
    for instance in ("vc0", "vc1"):
        native = configuration(placed, instance)
        assert native["sync"]["fromHost"]["nodes"]["enabled"] is False
        assert native["controlPlane"]["advanced"]["virtualScheduler"]["enabled"] is False
        assert native["controlPlane"]["distro"]["k8s"]["scheduler"]["enabled"] is False
        assert native["sync"]["toHost"]["pods"]["hybridScheduling"]["enabled"] is False
        assert native["sync"]["fromHost"]["nodes"]["selector"]["labels"] == {"pool": "vcluster"}
        assert native["sync"]["toHost"]["pods"]["enforceTolerations"] == ["dedicated=vcluster:NoSchedule"]
        pod = manifest(placed, resource_name("vcluster", "s-joe", instance, "statefulset"))["spec"]["template"]["spec"]
        assert all(pod[key] == value for key, value in placement["controlPlane"].items())
        assert "patches" not in native["sync"]["toHost"]["pods"]
    print("PASS placement settings apply to control planes and workloads")
    return placed_env, placed


def check_hibernation(args, env, source, baseline):
    source = deepcopy(source)
    source["metadata"]["generation"] = 2
    source["spec"]["vclusters"]["vc0"]["hibernated"] = True
    policies = [deepcopy(body) for key, body in baseline.items()
                if "placement-policy" in key]
    for policy in policies:
        policy["status"] = {"conditions": [{"type": "Ready", "status": "True"}]}
    sleeping = render(args, env, source, policies, include_composite=True)
    control = resource_name("vcluster", "s-joe", "vc0", "statefulset")
    provider = resource_name("s-joe", "vcluster", "vc0")

    def state(resources):
        return next(s for s in resources["composite"]["status"]["vclusters"] if s["name"] == "vc0")

    def observed(resources, **replacements):
        result = []
        for key, body in {**resources, **replacements}.items():
            if key == "composite":
                continue
            body = deepcopy(body)
            if "placement-policy" in key:
                body["status"] = {"conditions": [{"type": "Ready", "status": "True"}]}
            result.append(body)
        return result

    def cleanup_keys(resources):
        return {key for key, body in resources.items()
                if body.get("metadata", {}).get("labels", {}).get(
                    "datalabs.versioneer.at/lifecycle") == "cleanup"}

    def lifecycle_request(resources):
        return json.loads(manifest(resources, control)["metadata"]["annotations"][
            "datalabs.versioneer.at/lifecycle-request"])

    job_key, = cleanup_keys(sleeping)
    assert manifest(sleeping, control)["spec"]["replicas"] == 0
    assert manifest(sleeping, resource_name("vcluster", "s-joe", "vc1", "statefulset"))["spec"]["replicas"] == 1
    assert manifest(sleeping, job_key)["spec"]["template"]["spec"]["nodeSelector"] == {"pool": "general"}
    assert manifest(sleeping, job_key)["spec"]["suspend"] is True
    assert state(sleeping)["phase"] == "Hibernating"
    for key, body in sleeping.items():
        if body.get("spec", {}).get("providerConfigRef", {}).get("name") == provider:
            assert body["metadata"]["annotations"]["crossplane.io/paused"] == "false"
            assert body["spec"]["managementPolicies"] == ["Observe"]
            assert {k: v for k, v in body["spec"].items() if k != "managementPolicies"} == {
                k: v for k, v in baseline[key]["spec"].items() if k != "managementPolicies"}
    for key in (resource_name("vcluster", "s-joe", "vc0", "data"), resource_name("volume", "s-joe", "analysis")):
        assert manifest(sleeping, key) == manifest(baseline, key)
    host_volume = sleeping[resource_name("volume", "s-joe", "analysis")]
    assert "crossplane.io/paused" not in host_volume["metadata"]["annotations"]
    assert [c["secretRef"] for c in connections(sleeping)] == [c["secretRef"] for c in connections(baseline)]
    assert not any(c["ready"] for c in connections(sleeping) if c["instance"] == "vc0")
    repeated = render(args, env, source, observed(sleeping), include_composite=True)
    assert manifest(repeated, control)["spec"]["replicas"] == 0
    assert job_key in repeated

    job = deepcopy(sleeping[job_key])
    host_job = deepcopy(manifest(sleeping, job_key))
    host_job["metadata"]["uid"] = "test-job-uid"
    host_job["status"] = {"conditions": [{"type": "Complete", "status": "True"}]}
    job["status"] = {"atProvider": {"manifest": host_job}}
    observation = observed(sleeping, **{job_key: job})
    complete = render(args, env, source, observation, include_composite=True)
    assert state(complete)["phase"] == "Hibernated"

    failed_job = deepcopy(job)
    failed_job["status"]["atProvider"]["manifest"]["status"] = {"conditions": [
        {"type": "Failed", "status": "True", "reason": "BackoffLimitExceeded"}]}
    failed = render(args, env, source, observed(sleeping, **{job_key: failed_job}), include_composite=True)
    assert state(failed)["phase"] == "Failed"
    assert "Pod logs" in state(failed)["message"]

    for previous, resources in ((sleeping, observed(sleeping)), (complete, observation)):
        reference_change = deepcopy(source)
        reference_change["metadata"]["generation"] = 3
        reference_change["status"] = previous["composite"]["status"]
        reference_change["spec"].setdefault("crossplane", {})["resourceRefs"] = [{
            "apiVersion": job["apiVersion"], "kind": job["kind"],
            "name": job["metadata"]["name"],
        }]
        retained = render(args, env, reference_change, resources, include_composite=True)
        assert cleanup_keys(retained) == {job_key}
        assert state(retained)["cleanupGeneration"] == 2
        assert state(retained)["observedGeneration"] == 3
        assert state(retained)["phase"] == state(previous)["phase"]
        assert lifecycle_request(retained) == {"generation": 2, "hibernated": True}
    print("PASS resource reference changes keep the same cleanup Job")

    interrupted_source = deepcopy(source)
    interrupted_source["status"] = complete["composite"]["status"]
    interrupted_source["metadata"]["generation"] = 3
    interrupted_source["spec"]["vclusters"]["vc0"]["hibernated"] = False
    applied_resume = render(args, env, interrupted_source, observation, include_composite=True)
    assert manifest(applied_resume, control)["spec"]["replicas"] == 1
    resumed_control = deepcopy(applied_resume[control])
    resumed_control["status"] = {"atProvider": {"manifest": manifest(sleeping, control)}}
    resumed_observation = observed(applied_resume, **{control: resumed_control, job_key: job})
    # Keep the old XR status after the resume request reaches the composed Object.
    interrupted_source["metadata"]["generation"] = 4
    interrupted_source["spec"]["vclusters"]["vc0"]["hibernated"] = True
    new_sleep = render(args, env, interrupted_source, resumed_observation, include_composite=True)
    assert state(new_sleep)["phase"] == "Hibernating"
    assert state(new_sleep)["cleanupGeneration"] == 4
    assert state(new_sleep)["cleanupJob"] != state(complete)["cleanupJob"]
    assert lifecycle_request(new_sleep) == {"generation": 4, "hibernated": True}
    interrupted_source["metadata"]["generation"] = 5
    repeated_sleep = render(args, env, interrupted_source, observed(new_sleep), include_composite=True)
    assert state(repeated_sleep)["phase"] == "Hibernating"
    assert state(repeated_sleep)["cleanupJob"] == state(new_sleep)["cleanupJob"]
    assert state(repeated_sleep)["cleanupGeneration"] == 4
    print("PASS a new hibernation starts fresh cleanup after an interrupted resume")

    resume_source = deepcopy(source)
    resume_source["status"] = complete["composite"]["status"]
    resume_source["spec"]["vclusters"]["vc0"]["hibernated"] = False
    resume_source["metadata"]["generation"] = 3
    missing_job = [body for body in observation if body["metadata"]["name"] != job["metadata"]["name"]]
    interrupted_creation = render(args, env, resume_source, missing_job, include_composite=True)
    assert manifest(interrupted_creation, control)["spec"]["replicas"] == 0
    assert manifest(interrupted_creation, job_key)["spec"]["suspend"] is True
    assert manifest(interrupted_creation, job_key)["spec"]["template"]["spec"]["containers"][0]["args"][-1] == "2"
    native_job = deepcopy(host_job)
    native_job["status"] = {}
    changed_env = deepcopy(env)
    changed_env["data"].setdefault("images", {})["vclusterCleanup"] = "registry.acme.com/tools/python:changed"
    recovered = render(args, [changed_env, native_job], resume_source, missing_job, include_composite=True)
    assert manifest(recovered, control)["spec"]["replicas"] == 0
    assert manifest(recovered, job_key)["spec"]["template"] == native_job["spec"]["template"]
    host_job["status"] = {"conditions": [{"type": "Suspended", "status": "True"}]}
    host_job["spec"]["suspend"] = True
    job["status"]["atProvider"]["manifest"] = host_job
    observation = observed(sleeping, **{job_key: job})
    pod = {"apiVersion": "v1", "kind": "Pod", "metadata": {
        "name": "test-old-cleanup", "namespace": "s-joe",
        "labels": {"batch.kubernetes.io/controller-uid": "test-job-uid"},
        "ownerReferences": [{"apiVersion": "batch/v1", "kind": "Job", "name": host_job["metadata"]["name"], "uid": "test-job-uid"}]},
        "status": {"phase": "Running"}}
    resuming = render(args, [env, pod], resume_source, observation, include_composite=True)
    assert state(resuming)["phase"] == "Resuming"
    assert manifest(resuming, control)["spec"]["replicas"] == 0
    assert manifest(resuming, job_key)["spec"]["suspend"] is True
    # A stale controller cannot release the gate while its Pod still runs.
    pod["metadata"]["deletionTimestamp"] = "2026-11-20T00:00:00Z"
    interrupted = render(args, [env, pod], resume_source, observation, include_composite=True)
    assert manifest(interrupted, control)["spec"]["replicas"] == 0
    pod["status"]["phase"] = "Failed"
    resumed = render(args, [env, pod], resume_source, observation, include_composite=True)
    assert manifest(resumed, control)["spec"]["replicas"] == 1
    assert job_key not in resumed
    assert manifest(resumed, resource_name("vcluster", "s-joe", "vc0", "data")) == manifest(baseline, resource_name("vcluster", "s-joe", "vc0", "data"))
    rapid_source = deepcopy(source)
    rapid_source["status"] = resumed["composite"]["status"]
    rapid_source["metadata"]["generation"] = 4
    rapid = render(args, [env, pod], rapid_source, observation, include_composite=True)
    assert manifest(rapid, control)["spec"]["replicas"] == 0
    assert state(rapid)["cleanupJob"] != state(complete)["cleanupJob"]
    check_admission(baseline, sleeping)
    print("PASS hibernation and resume preserve storage and report cleanup failures")


def check_admission(placed, sleeping):
    placement = manifest(placed, resource_name("vcluster", "s-joe", "vc0", "placement-policy"))
    cleanup = manifest(sleeping, resource_name("vcluster", "s-joe", "vc0", "cleanup-policy"))
    tests = []
    values = {"request": {"operation": "CREATE", "userInfo": {
        "username": "system:serviceaccount:s-joe:vc-vcluster-vc0"}},
        "object": {"spec": {"nodeSelector": {"pool": "vcluster", "disk": "ssd"},
                            "tolerations": [{"key": "existing", "operator": "Exists"},
                                            {"key": "dedicated", "value": "vcluster", "effect": "NoSchedule"}]}},
        "oldObject": {}, "params": {}}

    def case(name, policy, data, allowed):
        tests.append({"Name": name, "Matches": [x["expression"] for x in policy["spec"]["matchConditions"]],
                      "Validations": [x["expression"] for x in policy["spec"]["validations"]],
                      "Values": deepcopy(data), "Allowed": allowed})

    case("compatible selectors and tolerations", placement, values, True)
    for name, field, value in (("wrong pool", "nodeSelector", {"pool": "general"}),
                               ("direct node assignment", "nodeName", "general-node"),
                               ("other scheduler", "schedulerName", "tenant-scheduler"),
                               ("missing toleration", "tolerations", [])):
        changed = deepcopy(values)
        changed["object"]["spec"][field] = value
        case(name, placement, changed, False)
    changed = deepcopy(values)
    changed["request"]["operation"] = "UPDATE"
    changed["oldObject"] = deepcopy(changed["object"])
    changed["object"]["spec"]["nodeName"] = "vcluster-node"
    changed["oldObject"]["spec"]["nodeName"] = "vcluster-node"
    case("syncer can update an already bound Pod", placement, changed, True)
    changed["object"]["spec"]["nodeName"] = "general-node"
    case("syncer cannot move a bound Pod", placement, changed, False)
    changed["request"]["userInfo"]["username"] = "system:serviceaccount:s-joe:other-service"
    case("other host identities are outside this policy", placement, changed, True)
    values = {"request": {"operation": "DELETE", "userInfo": {
        "username": "system:serviceaccount:s-joe:" + resource_name("vc-cleanup", "vc0", limit=45)}},
        "object": None, "params": {"metadata": {"name": "vcluster-vc0", "uid": "service-uid"}},
        "oldObject": {"metadata": {"ownerReferences": [{"apiVersion": "v1", "kind": "Service",
                   "name": "vcluster-vc0", "uid": "service-uid"}]}}}
    case("delete this instance's Pod", cleanup, values, True)
    values["oldObject"]["metadata"]["ownerReferences"][0]["uid"] = "other-instance-uid"
    case("cannot delete another instance despite a matching name", cleanup, values, False)
    values["oldObject"]["metadata"] = {"labels": {"vcluster.loft.sh/managed-by": "vcluster-vc0"}}
    case("tenant labels cannot authorize cleanup", cleanup, values, False)
    run_admission(tests)


def main():
    args = arguments()
    env = environment()
    env["data"].update({"packageR": {"enabled": False}, "registry": {"enabled": False}})
    env["data"]["vcluster"] = {}
    env["data"]["volumes"] = {"storageClasses": {"allowed": ["standard"]},
                              "snapshotClassName": "workspace-snapshots"}
    group = {"name": "demo", "namespace": "demo", "role": "edit"}
    source = {
        "apiVersion": "versioneer.at/v1",
        "kind": "Datalab",
        "metadata": {"name": "s-joe", "namespace": "workspace"},
        "spec": {
            "users": ["joe"],
            "volumes": {"analysis": {"storage": "2Gi", "backups": True}},
            "vclusters": {
                key: {"groups": [group], "storage": "2Gi"} for key in ("vc0", "vc1")
            },
        },
    }
    resources = render(args, env, source, [], include_composite=True)
    check_volume_bindings(args, env, source, resources)
    check_instance_isolation(resources)
    check_membership(args, env, source, resources)
    check_secret_bindings(args, env, source)
    check_control_plane_settings(args, env, source, resources)
    check_public_profiles(args, env, source, resources)
    check_instance_removal(args, env, source, resources)
    check_name_collisions(args, env, source)
    placed_env, placed = check_placement(args, env, source, resources)
    check_hibernation(args, placed_env, source, placed)


if __name__ == "__main__":
    main()
