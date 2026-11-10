# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Check environment control of direct services, security, and storage quota."""

from copy import deepcopy

from render import arguments, environment, manifest, render


def main():
    args = arguments()
    env = environment()
    env["metadata"]["name"] = "datalab-custom"
    env["data"]["defaults"] = {
        "data": {"enabled": True, "readOnlyMount": True},
        "registry": {"enabled": False},
        "overallQuota": {"storage": "50Gi", "hard": {"requests.cpu": "2", "requests.memory": "4Gi"}},
        "limitRange": {"default": {"memory": "1Gi"}, "defaultRequest": {"cpu": "50m"}},
        "security": {"policy": "restricted", "externalEgress": False},
    }
    env["data"]["network"] = {
        "externalEgressCIDRs": ["0.0.0.0/0", "::/0"],
        "serviceCIDR": "10.96.0.0/16",
        "podCIDRs": ["10.244.0.0/16"],
        "blacklistIPs": ["169.254.169.254/32", "fd00:ec2::254/128"],
        "internalIngress": [{
            "namespace": "operations",
            "targetPodSelector": {"matchLabels": {"app": "metrics"}},
            "ports": [{"port": 9000, "protocol": "TCP"}],
        }],
    }
    env["data"]["images"] = {
        "packageR": "test-images/package-r:custom", "registry": "test-images/registry:custom",
        "rclone": "test-images/rclone:custom", "oauth2Proxy": "test-images/oauth2-proxy:custom",
    }
    source = {
        "apiVersion": "versioneer.at/v1", "kind": "Datalab",
        "metadata": {"name": "s-joe", "annotations": {"datalabs.versioneer.at/environment": "datalab-custom"}},
        "spec": {"users": ["joe"]},
    }
    resources = render(args, env, source)
    namespace = manifest(resources, "namespace-s-joe")
    assert namespace["metadata"]["labels"]["pod-security.kubernetes.io/enforce"] == "restricted"
    assert manifest(resources, "networkpolicy-s-joe-deny-ingress")["spec"] == {
        "podSelector": {}, "policyTypes": ["Ingress"], "ingress": [],
    }
    assert manifest(resources, "networkpolicy-s-joe-allow-namespace-ingress")["spec"] == {
        "podSelector": {}, "policyTypes": ["Ingress"],
        "ingress": [{"from": [{"podSelector": {}}]}],
    }
    assert "networkpolicy-s-joe-allow-external-egress" not in resources
    quota = manifest(resources, "resourcequota-s-joe-overall-storage")
    assert quota["spec"]["hard"] == {
        "requests.storage": "50Gi", "requests.cpu": "2", "requests.memory": "4Gi",
        "limits.cpu": "16", "limits.memory": "32Gi",
    }
    limits = manifest(resources, "limitrange-s-joe")["spec"]["limits"]
    assert limits[0]["default"]["memory"] == "1Gi"
    assert limits[0]["defaultRequest"]["cpu"] == "50m"
    ingress = [
        item["spec"]["forProvider"]["manifest"]["spec"]
        for key, item in resources.items()
        if key.startswith("networkpolicy-s-joe-allow-internal-ingress")
    ]
    assert len(ingress) == 1
    assert ingress[0]["podSelector"] == {"matchLabels": {"app": "metrics"}}
    assert ingress[0]["ingress"] == [{
        "from": [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "operations"}}}],
        "ports": [{"port": 9000, "protocol": "TCP"}],
    }]
    ingress_name = next(
        item["spec"]["forProvider"]["manifest"]["metadata"]["name"]
        for key, item in resources.items()
        if key.startswith("networkpolicy-s-joe-allow-internal-ingress")
    )
    containers = manifest(resources, "data-deployment-s-joe")["spec"]["template"]["spec"]["initContainers"]
    assert not any("--perm.create=true" in arg for c in containers for arg in c.get("args", []))
    print("PASS environment security, quota, and read-only Data", flush=True)

    deployment = manifest(resources, "data-deployment-s-joe")["spec"]["template"]["spec"]
    assert deployment["initContainers"][0]["image"] == env["data"]["images"]["packageR"]
    for key in ("data-deployment-s-joe", "data-s3-deployment-s-joe"):
        containers = manifest(resources, key)["spec"]["template"]["spec"]["containers"]
        assert next(c["image"] for c in containers if c["name"] == "oauth2-proxy") == env["data"]["images"]["oauth2Proxy"]
    assert manifest(resources, "data-s3-deployment-s-joe")["spec"]["template"]["spec"]["containers"][0]["image"] == env["data"]["images"]["rclone"]
    env["data"]["defaults"]["registry"]["enabled"] = True
    observer = deepcopy(resources["observe-runtime-storage-secret-s-joe"])
    observer["status"] = {"atProvider": {"manifest": manifest(resources, "runtime-storage-secret-s-joe")}}
    with_registry = render(args, env, source, [observer])
    assert manifest(with_registry, "registry-deployment-s-joe")["spec"]["template"]["spec"]["containers"][0]["image"] == env["data"]["images"]["registry"]
    env["data"]["defaults"]["registry"]["enabled"] = False
    print("PASS environment service image overrides", flush=True)

    env["data"]["defaults"]["data"]["readOnlyMount"] = False
    env["data"]["defaults"]["security"]["externalEgress"] = True
    resources = render(args, env, source)
    assert "networkpolicy-s-joe-allow-external-egress" in resources
    egress = manifest(resources, "networkpolicy-s-joe-allow-external-egress")["spec"]["egress"]
    blocks = {rule["to"][0]["ipBlock"]["cidr"]: rule["to"][0]["ipBlock"]["except"] for rule in egress}
    assert set(blocks["0.0.0.0/0"]) == {"10.96.0.0/16", "10.244.0.0/16", "169.254.169.254/32"}
    assert blocks["::/0"] == ["fd00:ec2::254/128"]
    containers = manifest(resources, "data-deployment-s-joe")["spec"]["template"]["spec"]["initContainers"]
    assert any("--perm.create=true" in arg for c in containers for arg in c.get("args", []))
    print("PASS environment writable Data and external egress", flush=True)

    env["data"]["defaults"]["data"]["enabled"] = False
    resources = render(args, env, source)
    for name in ("data-deployment-s-joe", "observe-runtime-storage-secret-s-joe"):
        assert name not in resources
    assert "namespace-s-joe" in resources
    print("PASS disabling Data preserves the service namespace", flush=True)

    env["data"]["network"]["excludePolicies"] = ["allow-internal-ingress", "allow-external-egress"]
    excluded = render(args, env, source)
    assert not any(key.startswith("networkpolicy-s-joe-allow-internal-ingress") for key in excluded)
    assert "networkpolicy-s-joe-allow-external-egress" not in excluded
    env["data"]["network"]["excludePolicies"] = [ingress_name]
    excluded = render(args, env, source)
    assert f"networkpolicy-s-joe-{ingress_name}" not in excluded
    assert "networkpolicy-s-joe-allow-external-egress" in excluded
    print("PASS targeted ingress, external CIDR exclusions, and policy exclusions", flush=True)

    for name in ("workspace", "default", "kube-public"):
        invalid = deepcopy(source)
        invalid["metadata"].update(name=name, namespace="workspace")
        render(args, env, invalid, observed=[], error="service namespace must differ")
    print("PASS claim and system namespaces are rejected", flush=True)


if __name__ == "__main__":
    main()
