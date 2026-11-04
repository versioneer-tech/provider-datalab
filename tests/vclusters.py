# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Check independent virtual clusters and legacy session coexistence."""

from copy import deepcopy
import base64
import hashlib
import json

from helpers import load_helpers

NAMING = load_helpers("_resource_name", "_vcluster_profile")
resource_name = NAMING["_resource_name"]
profile_name = NAMING["_vcluster_profile"]

from render import arguments, environment, manifest, render


def main():
    args = arguments()
    env = environment()
    env["data"]["vcluster"] = {"storageClasses": {"allowed": ["standard"]}}
    group = {"name": "demo", "namespace": "demo", "role": "edit"}
    source = {
        "apiVersion": "pkg.internal/v1beta2",
        "kind": "Datalab",
        "metadata": {"name": "s-joe", "namespace": "workspace"},
        "spec": {
            "users": ["joe"],
            "sessions": [{"name": "work"}],
            "vclusters": {
                key: {"groups": [group], "storage": "2Gi"} for key in ("vc0", "vc1")
            },
        },
    }
    observed = [
        {
            "apiVersion": "kubernetes.m.crossplane.io/v1alpha1",
            "kind": "Object",
            "metadata": {
                "name": "workshopenvironment-s-joe",
                "namespace": "workspace",
                "annotations": {
                    "crossplane.io/composition-resource-name": "workshopenvironment-s-joe"
                },
            },
            "status": {
                "atProvider": {
                    "manifest": {"status": {"educates": {"namespace": "s-joe-runtime"}}}
                }
            },
        }
    ]
    resources = render(args, env, source, observed, include_composite=True)
    assert "workshopsession-s-joe-work" in resources
    assert manifest(resources, "workshop-s-joe")["spec"]["session"]["applications"][
        "vcluster"
    ]["enabled"]
    for instance in ("vc0", "vc1"):

        def key(suffix):
            return resource_name("vcluster", "s-joe", instance, suffix)

        runtime = f"vcluster-{instance}"
        statefulset = manifest(resources, key("statefulset"))
        assert statefulset["metadata"]["namespace"] == "s-joe-runtime"
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
        assert tls["validation"]["hostname"] == f"{runtime}.s-joe-runtime.svc"
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
    assert len([c for c in resources["composite"]["status"]["connections"] if c["type"] == "vcluster"]) == 4
    assert resources["composite"]["status"]["sessions"]["work"]["state"] == "started"
    print(
        "PASS two virtual clusters have separate routes, identities, selectors, and session status"
    )

    def user_roles(rendered):
        return {
            ref["name"]
            for ref in rendered["keycloak-roles-user-s-joe"]["spec"]["forProvider"]["roleIdsRefs"]
        }

    implicit = deepcopy(source)
    implicit["spec"]["users"] = ["joe", "jane"]
    implicit["spec"]["vclusters"] = {"vc0": {}, "vc1": {"groups": []}}
    automatic = render(args, env, implicit, observed, include_composite=True)
    assert automatic["keycloak-memberships-users-s-joe"]["spec"]["forProvider"]["members"] == ["joe", "jane"]
    assert user_roles(automatic) == {
        "s-joe-ws-access",
        *(profile_name("s-joe", instance, "cluster-admin") for instance in ("vc0", "vc1")),
    }
    assert all(
        ref["policy"]["resolve"] == "Always"
        for ref in automatic["keycloak-roles-user-s-joe"]["spec"]["forProvider"]["roleIdsRefs"]
    )
    for instance in ("vc0", "vc1"):
        profile = profile_name("s-joe", instance, "cluster-admin")
        assert automatic[f"keycloak-vcluster-role-{profile}"]["spec"]["forProvider"]["name"] == f"vcluster_{instance}_cluster-admin"
        mapper_name = resource_name("vcluster", "s-joe", instance, "users-scope")
        mapper = automatic[f"keycloak-vcluster-user-role-mapper-{mapper_name}"]["spec"]["forProvider"]
        assert mapper["clientIdRef"]["name"] == "s-joe"
        assert mapper["roleIdRef"]["name"] == profile
        bindings = [
            body["spec"]["forProvider"]["manifest"]
            for body in automatic.values()
            if body.get("kind") == "Object"
            and body["metadata"].get("labels", {}).get("datalabs.pkg.internal/vcluster") == instance
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
    disabled = render(args, env, implicit, observed)
    assert user_roles(disabled) == {"s-joe-ws-access"}
    assert disabled["keycloak-memberships-users-s-joe"]["spec"]["forProvider"]["members"] == ["joe"]
    assert not any(key.startswith("keycloak-vcluster-") for key in disabled)
    assert disabled["keycloak-service-account-role-api-s-joe-ws-api"]["spec"] == automatic["keycloak-service-account-role-api-s-joe-ws-api"]["spec"]
    vacant_source = deepcopy(source)
    vacant_source["spec"]["users"] = []
    vacant = render(args, env, vacant_source, observed)
    assert "keycloak-memberships-users-s-joe" not in vacant
    assert "keycloak-memberships-admins-s-joe-admin" not in vacant
    assert user_roles(vacant) == user_roles(automatic)
    assert manifest(vacant, resource_name("vcluster", "s-joe", "vc0", "statefulset")) == manifest(resources, resource_name("vcluster", "s-joe", "vc0", "statefulset"))
    print("PASS Datalab members receive built-in administration without explicit profiles; removal clears grants")

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
        "observe-custom-secret", "s-joe", "s-joe-runtime", "github-development"
    )
    custom_source = {
        "apiVersion": "kubernetes.m.crossplane.io/v1alpha1", "kind": "Object",
        "metadata": {"name": custom_key, "namespace": "workspace",
                     "annotations": {"crossplane.io/composition-resource-name": custom_key}},
        "status": {
            "conditions": [{"type": "Ready", "status": "True"}],
            "atProvider": {"manifest": {
                "apiVersion": "v1", "kind": "Secret",
                "metadata": {"namespace": "s-joe-runtime", "name": "github-development"},
            }},
        },
    }
    bound = render(args, bound_env, bound_source, [*observed, custom_source], include_composite=True)
    connections = bound["composite"]["status"]["connections"]
    custom = [c for c in connections if c["type"] == "custom"]
    assert custom == [{"name": "github-development", "type": "custom", "ready": True,
                       "secretRef": {"namespace": "s-joe-runtime", "name": "github-development"}}]
    assert not next(c for c in connections if c["type"] == "postgres")["ready"]

    def native_secrets(rendered, instance):
        config = manifest(rendered, resource_name("vcluster", "s-joe", instance, "config"))
        return json.loads(base64.b64decode(config["data"]["config.yaml"]))["sync"]["fromHost"]["secrets"]

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

    def settings(rendered, instance="vc0"):
        def key(suffix):
            return resource_name("vcluster", "s-joe", instance, suffix)

        secret = manifest(rendered, key("config"))
        assert "stringData" not in secret
        configuration_text = base64.b64decode(secret["data"]["config.yaml"]).decode()
        configuration = json.loads(configuration_text)
        pod = manifest(rendered, key("statefulset"))["spec"]["template"]
        authentication = manifest(rendered, key("authentication"))["data"]["authentication.json"]
        checksum = pod["metadata"]["annotations"]["datalabs.pkg.internal/configuration-checksum"]
        assert checksum == hashlib.sha256((configuration_text + authentication).encode()).hexdigest()
        assert configuration["controlPlane"]["statefulSet"]["resources"] == pod["spec"]["containers"][0]["resources"]
        return configuration["controlPlane"], checksum

    defaults, _ = settings(resources)
    assert defaults["backingStore"]["database"]["embedded"] == {"enabled": False, "extraArgs": []}
    assert defaults["statefulSet"]["resources"] == {
        "requests": {"cpu": "200m", "memory": "1Gi", "ephemeral-storage": "1Gi"},
        "limits": {"cpu": "4", "memory": "4Gi", "ephemeral-storage": "10Gi"},
    }
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

    for field, value in (
        ("enabled", False),
        ("dataSource", embedded["dataSource"].replace("TRUNCATE", "WAL")),
        ("extraArgs", ["--datastore-max-open-connections=3", "--datastore-max-idle-connections=1"]),
    ):
        changed_env = deepcopy(tuned_env)
        changed_env["data"]["vcluster"]["backingStore"]["database"]["embedded"][field] = value
        changed = render(args, changed_env, source, observed)
        control_plane, checksum = settings(changed)
        assert control_plane["backingStore"]["database"]["embedded"][field] == value
        assert checksum != settings(tuned)[1], field
    for section, field, value in (
        ("requests", "cpu", "300m"),
        ("requests", "memory", "2Gi"),
        ("limits", "cpu", "3"),
        ("limits", "memory", "3Gi"),
    ):
        changed_env = deepcopy(tuned_env)
        changed_env["data"]["vcluster"]["resources"] = {section: {field: value}}
        changed = render(args, changed_env, source, observed)
        control_plane, checksum = settings(changed)
        expected = deepcopy(defaults["statefulSet"]["resources"])
        expected[section][field] = value
        assert control_plane["statefulSet"]["resources"] == expected
        assert checksum != settings(tuned)[1], (section, field)
    reordered_env = deepcopy(tuned_env)
    reordered_env["data"]["vcluster"]["backingStore"]["database"]["embedded"] = dict(reversed(list(embedded.items())))
    assert settings(render(args, reordered_env, source, observed)) == settings(tuned)
    print("PASS each database and resource option triggers a stable configuration checksum")

    ready_observed = deepcopy(observed)
    for instance in ("vc0", "vc1"):
        ready_observed.append(
            {
                "apiVersion": "kubernetes.m.crossplane.io/v1alpha1",
                "kind": "Object",
                "metadata": {
                    "name": resource_name(
                        "vcluster", "s-joe", instance, "observe-client-demo"
                    ),
                    "namespace": "workspace",
                    "annotations": {
                        "crossplane.io/composition-resource-name": resource_name(
                            "vcluster", "s-joe", instance, "observe-client-demo"
                        )
                    },
                },
                "status": {
                    "atProvider": {
                        "manifest": {
                            "data": {
                                "clientSecret": base64.b64encode(
                                    f"{instance}-test-password".encode()
                                ).decode()
                            }
                        }
                    }
                },
            }
        )
    resources = render(args, env, source, ready_observed, include_composite=True)
    for instance in ("vc0", "vc1"):
        secret = resources[
            resource_name("connection", profile_name("s-joe", instance, "demo"))
        ]
        config = json.loads(secret["stringData"]["kubeconfig"])
        assert (
            config["clusters"][0]["cluster"]["server"]
            == f"https://s-joe.lab.acme.com/.{instance}"
        )
        assert secret["stringData"]["client-secret"] == f"{instance}-test-password"

    reduced = deepcopy(source)
    del reduced["spec"]["vclusters"]["vc0"]
    reduced_resources = render(args, env, reduced, observed)
    assert "vcluster-s-joe-vc0-statefulset-1987a0016d" not in reduced_resources
    assert user_roles(reduced_resources) == {
        "s-joe-ws-access", profile_name("s-joe", "vc1", "cluster-admin")
    }
    assert manifest(
        reduced_resources, "vcluster-s-joe-vc1-statefulset-b6c1325e58"
    ) == manifest(resources, "vcluster-s-joe-vc1-statefulset-b6c1325e58")
    assert manifest(reduced_resources, "workshopsession-s-joe-work") == manifest(
        resources, "workshopsession-s-joe-work"
    )
    print("PASS removing one instance preserves the other instance and session")

    pending = render(args, env, source, [])
    assert "vcluster-s-joe-vc0-statefulset-1987a0016d" not in pending
    assert "workshopenvironment-s-joe" in pending
    print("PASS native runtimes wait for the Educates namespace")

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
    distinct = render(args, env, hyphenated, observed, include_composite=True)
    connections = [c for c in distinct["composite"]["status"]["connections"] if c["type"] == "vcluster"]
    assert len({c["name"] for c in connections}) == 8
    assert len({c["secretRef"]["name"] for c in connections}) == 8
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
        "PASS hyphenated instance and profile names keep separate host objects and credentials"
    )


if __name__ == "__main__":
    main()
