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
        "overallQuota": {"storage": "50Gi"},
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
    source = {
        "apiVersion": "pkg.internal/v1", "kind": "Datalab",
        "metadata": {"name": "s-joe", "annotations": {"datalabs.pkg.internal/environment": "datalab-custom"}},
        "spec": {
            "users": ["joe"],
            "data": {"enabled": False, "readOnlyMount": False},
            "security": {"policy": "privileged", "externalEgress": True},
            "overallQuota": {"storage": "1Gi"},
        },
    }
    resources = render(args, env, source)
    namespace = manifest(resources, "namespace-s-joe")
    assert namespace["metadata"]["labels"]["pod-security.kubernetes.io/enforce"] == "restricted"
    assert "networkpolicy-s-joe-allow-external-egress" not in resources
    quota = manifest(resources, "resourcequota-s-joe-overall-storage")
    assert quota["spec"]["hard"]["requests.storage"] == "50Gi"
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
