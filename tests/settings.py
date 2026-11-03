# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Check that environment settings control sessions and Data."""

from render import arguments, environment, manifest, render


def main():
    args = arguments()
    env = environment()
    env["metadata"]["name"] = "datalab-custom"
    env["data"]["defaults"] = {
        "data": {"enabled": True, "readOnlyMount": True},
        "quota": {"memory": "7Gi", "storage": "9Gi", "budget": "large"},
        "overallQuota": {"storage": "50Gi"},
        "security": {"policy": "restricted", "externalEgress": False, "kubernetesAccess": False,
                     "kubernetesRole": "view"},
        "registry": {"enabled": True, "storage": "3Gi"},
        "persistence": {"storageClassName": "sbs-default-retain"},
        "files": [{"git": {"url": "https://github.com/versioneer-tech/datalab-example", "ref": "origin/main"}}],
    }
    env["data"]["storageClasses"] = {"allowed": ["sbs-default", "sbs-default-retain"]}
    env["data"]["network"] = {"externalEgressCIDRs": ["0.0.0.0/0"]}
    source = {
        "apiVersion": "pkg.internal/v1beta2", "kind": "Datalab",
        "metadata": {"name": "s-joe", "annotations": {"datalabs.pkg.internal/environment": "datalab-custom"}},
        "spec": {
            "users": ["joe"], "sessions": [{"name": "default"}], "vcluster": False,
            "data": {"enabled": False, "readOnlyMount": False},
            "security": {"policy": "privileged", "externalEgress": True, "kubernetesAccess": True,
                         "kubernetesRole": "admin"},
            "quota": {"memory": "1Gi", "storage": "1Gi", "budget": "small"},
            "overallQuota": {"storage": "1Gi"}, "registry": {"enabled": False},
            "persistence": {"storageClassName": "sbs-default"}, "files": [],
        },
    }
    # Old XR fields must not override the operator's environment settings.
    resources = render(args, env, source)
    workshop = manifest(resources, "workshop-s-joe")["spec"]
    session = workshop["session"]
    assert session["resources"]["memory"] == "7Gi"
    assert session["namespaces"]["budget"] == "large"
    assert session["namespaces"]["role"] == "view"
    assert session["namespaces"]["security"] == {"policy": "restricted", "token": {"enabled": False}}
    assert session["applications"]["registry"] == {"enabled": True, "storage": "3Gi"}
    assert session["applications"]["vcluster"]["enabled"] is True
    assert "docker" not in session["applications"]
    policies = {item["metadata"]["name"] for item in workshop["environment"]["objects"]}
    assert "allow-external-egress" not in policies
    assert "allow-vcluster-egress" in policies
    assert workshop["workshop"]["files"] == env["data"]["defaults"]["files"]
    pvc = manifest(resources, "persistentvolumeclaim-s-joe-default-persistent")["spec"]
    assert pvc["resources"]["requests"]["storage"] == "9Gi"
    assert pvc["storageClassName"] == "sbs-default-retain"
    quota = manifest(resources, "resourcequota-s-joe-overall-storage")
    assert quota["spec"]["hard"]["requests.storage"] == "50Gi"
    deployment = manifest(resources, "data-deployment-s-joe")
    containers = deployment["spec"]["template"]["spec"]["initContainers"]
    assert not any("--perm.create=true" in arg for container in containers for arg in container.get("args", []))
    session = manifest(resources, "workshopsession-s-joe-default")
    assert any(entry["name"] == "KUBECONFIG" for entry in session["spec"]["session"]["env"])
    print("PASS environment session, security, storage, and quota settings", flush=True)

    env["data"]["defaults"]["vcluster"] = {"enabled": False}
    env["data"]["defaults"]["data"]["readOnlyMount"] = False
    source["spec"]["vcluster"] = {"enabled": True}
    source["spec"]["data"]["readOnlyMount"] = True
    resources = render(args, env, source)
    workshop = manifest(resources, "workshop-s-joe")["spec"]
    assert workshop["session"]["applications"]["vcluster"]["enabled"] is False
    assert "allow-vcluster-egress" not in {item["metadata"]["name"] for item in workshop["environment"]["objects"]}
    session = manifest(resources, "workshopsession-s-joe-default")
    assert not any(entry["name"] == "KUBECONFIG" for entry in session["spec"]["session"].get("env", []))
    containers = manifest(resources, "data-deployment-s-joe")["spec"]["template"]["spec"]["initContainers"]
    assert any("--perm.create=true" in arg for container in containers for arg in container.get("args", []))
    print("PASS environment vCluster toggle and writable Data", flush=True)

    env["data"]["defaults"]["data"]["enabled"] = False
    env["data"]["defaults"]["registry"]["enabled"] = False
    source["spec"]["registry"]["enabled"] = True
    source["spec"]["data"]["enabled"] = True
    resources = render(args, env, source)
    for name in ("data-deployment-s-joe", "observe-runtime-storage-secret-s-joe"):
        assert name not in resources
    assert not any(item["metadata"]["name"] == "s-joe-s-joe-audience" for item in resources.values())
    workshop = manifest(resources, "workshop-s-joe")["spec"]
    assert "registry" not in workshop["session"]["applications"]
    assert not any(dashboard["name"] == "Data" for dashboard in workshop["session"]["dashboards"])
    print("PASS environment Data and registry toggles", flush=True)


if __name__ == "__main__":
    main()
