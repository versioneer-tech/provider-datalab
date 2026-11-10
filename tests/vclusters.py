# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Check independent virtual clusters, access, and instance removal."""

from copy import deepcopy
import base64
import json
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
        bundle = configuration(resources, instance)["experimental"]["deploy"]["vcluster"]["manifests"]
        installed = list(yaml.safe_load_all(bundle))
        crds = {item["metadata"]["name"] for item in installed if item["kind"] == "CustomResourceDefinition"}
        assert crds == {
            "sandboxes.agents.x-k8s.io", "sandboxclaims.extensions.agents.x-k8s.io",
            "sandboxwarmpools.extensions.agents.x-k8s.io", "sandboxtemplates.extensions.agents.x-k8s.io",
        }
        controller = next(item for item in installed if item["kind"] == "Deployment")
        assert controller["spec"]["template"]["spec"]["containers"][0]["image"].endswith(":v1.0.10")
        template = manifest(resources, resource_name("vcluster", "s-joe", instance, "access", "sandbox-template-demo"))
        pod = template["spec"]["podTemplate"]["spec"]
        assert pod["containers"][0]["name"] == "sandboxd"
        assert pod["automountServiceAccountToken"] is False
        assert (resource_name("vcluster", "s-joe", instance, "access", "session-analysis") in resources) == (instance == "vc0")
    pvc = manifest(resources, resource_name("vcluster", "s-joe", "vc0", "access", "session-analysis"))
    assert pvc["metadata"] == {"name": "session-analysis", "namespace": "demo"}
    assert pvc["spec"]["resources"]["requests"]["storage"] == "2Gi"
    assert pvc["spec"]["storageClassName"] == "standard"
    assert resources["composite"]["status"]["sessions"] == [{
        "name": "analysis", "vcluster": "vc0", "namespace": "demo", "pvcName": "session-analysis",
    }]
    print("PASS virtual clusters have separate routes, roles, and session storage")


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
    compatible = render(args, env, explicit, observed, include_composite=True)
    assert set(compatible) == set(automatic)
    assert all(body.get("spec") == automatic[key].get("spec") for key, body in compatible.items() if key != "composite")
    implicit["spec"]["users"].remove("jane")
    implicit["spec"]["vclusters"] = {}
    implicit["spec"]["sessions"] = []
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
    bound_source["spec"]["databases"] = {"pg0": {"names": ["analytics"]}}
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
        "dataSource": "sqlite:///data/state.db?_journal=TRUNCATE&_locking=NORMAL&cache=shared&_busy_timeout=30000&_txlock=immediate&_synchronous=FULL",
        "extraArgs": ["--datastore-max-open-connections=2", "--datastore-max-idle-connections=1"],
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
    resource_env["data"]["images"] = {
        "sandbox": "test-images/sandbox:custom",
        "sandboxd": "test-images/sandboxd:custom",
    }
    changed = render(args, resource_env, source, observed)
    expected = {
        section: {**defaults["statefulSet"]["resources"][section], **values}
        for section, values in resource_overrides.items()
    }
    for instance in ("vc0", "vc1"):
        control_plane, checksum = settings(changed, instance)
        assert control_plane["statefulSet"]["resources"] == expected
        assert checksum != settings(tuned, instance)[1]
        installed = yaml.safe_load_all(
            configuration(changed, instance)["experimental"]["deploy"]["vcluster"]["manifests"]
        )
        controller = next(item for item in installed if item["kind"] == "Deployment")
        assert controller["spec"]["template"]["spec"]["containers"][0]["image"] == resource_env["data"]["images"]["sandbox"]
        for target in ("default", "demo"):
            template = manifest(changed, resource_name(
                "vcluster", "s-joe", instance, "access", f"sandbox-template-{target}"
            ))
            assert template["spec"]["podTemplate"]["spec"]["containers"][0]["image"] == resource_env["data"]["images"]["sandboxd"]
    reordered_env = deepcopy(tuned_env)
    reordered_env["data"]["vcluster"]["backingStore"]["database"]["embedded"] = dict(reversed(list(embedded.items())))
    assert settings(render(args, reordered_env, source, observed)) == settings(tuned)
    print("PASS resource and Sandbox image overrides reach both instances; reordered settings keep the rollout checksum")


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
    print("PASS profiles contain no credentials and become ready without credential observers or vcluster account grants")


def check_instance_removal(args, env, source, resources):
    reduced = deepcopy(source)
    del reduced["spec"]["vclusters"]["vc0"]
    reduced["spec"]["sessions"] = []
    reduced_resources = render(args, env, reduced, [])
    assert resource_name("vcluster", "s-joe", "vc0", "statefulset") not in reduced_resources
    assert user_roles(reduced_resources) == {
        "s-joe-ws-access", "s-joe-ws-api", profile_name("s-joe", "vc1", "demo")
    }
    assert manifest(
        reduced_resources, resource_name("vcluster", "s-joe", "vc1", "statefulset")
    ) == manifest(resources, resource_name("vcluster", "s-joe", "vc1", "statefulset"))
    print("PASS removing one instance preserves the other instance")


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
    assert len([body for body in host_objects if body["kind"] == "ServiceAccount"]) == 8
    print(
        "PASS hyphenated instance and profile names keep separate host objects and connection references"
    )


def main():
    args = arguments()
    env = environment()
    env["data"]["vcluster"] = {"storageClasses": {"allowed": ["standard"]}}
    group = {"name": "demo", "namespace": "demo", "role": "edit"}
    source = {
        "apiVersion": "versioneer.at/v1",
        "kind": "Datalab",
        "metadata": {"name": "s-joe", "namespace": "workspace"},
        "spec": {
            "users": ["joe"],
            "sessions": [{"name": "analysis", "vcluster": "vc0", "namespace": "demo", "pvcSize": "2Gi"}],
            "vclusters": {
                key: {"groups": [group], "storage": "2Gi"} for key in ("vc0", "vc1")
            },
        },
    }
    resources = render(args, env, source, [], include_composite=True)
    check_instance_isolation(resources)
    check_membership(args, env, source, resources)
    check_secret_bindings(args, env, source)
    check_control_plane_settings(args, env, source, resources)
    check_public_profiles(args, env, source, resources)
    check_instance_removal(args, env, source, resources)
    check_name_collisions(args, env, source)


if __name__ == "__main__":
    main()
