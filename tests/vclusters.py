# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Check virtual cluster isolation, access profiles, and instance removal."""

from copy import deepcopy
import base64
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
        "apiVersion": "pkg.internal/v1",
        "kind": "Datalab",
        "metadata": {"name": "s-joe", "namespace": "workspace"},
        "spec": {
            "users": ["joe"],
            "vclusters": {
                key: {"groups": [group], "storage": "2Gi"} for key in ("vc0", "vc1")
            },
        },
    }
    observed = []
    resources = render(args, env, source, observed, include_composite=True)
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
            f"vcluster:{instance}:demo"
            in authentication["jwt"][0]["claimValidationRules"][0]["expression"]
        )
        other = "vc1" if instance == "vc0" else "vc0"
        assert (
            f"vcluster:{other}:demo"
            not in authentication["jwt"][0]["claimValidationRules"][0]["expression"]
        )
    assert len([c for c in resources["composite"]["status"]["connections"] if c["type"] == "vcluster"]) == 2
    print(
        "PASS two virtual clusters have separate routes, identities, and selectors"
    )

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
    assert manifest(
        reduced_resources, "vcluster-s-joe-vc1-statefulset-b6c1325e58"
    ) == manifest(resources, "vcluster-s-joe-vc1-statefulset-b6c1325e58")
    print("PASS removing one instance preserves the other instance")

    headless = deepcopy(source)
    headless["spec"]["users"] = []
    headless_resources = render(args, env, headless, [])
    assert manifest(headless_resources, "namespace-s-joe")["metadata"]["name"] == "s-joe"
    assert not any(item.get("kind") == "Memberships" for item in headless_resources.values())
    print("PASS services provision without user memberships")

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
    assert len({c["name"] for c in connections}) == 4
    assert len({c["secretRef"]["name"] for c in connections}) == 4
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
