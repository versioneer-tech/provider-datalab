# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Check that environment settings control sessions and Data."""

import base64
from pathlib import Path

import yaml

from render import arguments, environment, manifest, render


def main():
    args = arguments()
    observed = list(yaml.safe_load_all(Path("tests/observed/001-lab.yaml").read_text()))
    for item in observed:
        if item["metadata"]["name"] == "observe-runtime-storage-secret-s-joe":
            item["status"]["atProvider"]["manifest"]["data"]["aws-credentials"] = base64.b64encode(
                b"[default]\naws_access_key_id = test-access-key\naws_secret_access_key = test-secret-key\n"
            ).decode()
    env = environment()
    env["metadata"]["name"] = "datalab-custom"
    env["data"]["defaults"] = {
        "data": {"enabled": True, "readOnlyMount": True},
        "quota": {"memory": "7Gi", "storage": "9Gi", "budget": "large"},
        "overallQuota": {"storage": "50Gi"},
        "security": {"policy": "restricted", "externalEgress": False, "kubernetesAccess": False,
                     "kubernetesRole": "view"},
        "registry": {"enabled": True},
        "persistence": {"storageClassName": "sbs-default-retain"},
        "files": [{"git": {"url": "https://github.com/versioneer-tech/datalab-example", "ref": "origin/main"}}],
    }
    env["data"]["storageClasses"] = {"allowed": ["sbs-default", "sbs-default-retain"]}
    env["data"]["network"] = {"externalEgressCIDRs": ["0.0.0.0/0"]}
    env["data"]["images"] = {"packageR": "test-images/package-r:custom", "registry": "test-images/registry:custom",
                             "rclone": "test-images/rclone:custom", "oauth2Proxy": "test-images/oauth2-proxy:custom"}
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
    resources = render(args, env, source, observed)
    workshop = manifest(resources, "workshop-s-joe")["spec"]
    session = workshop["session"]
    assert session["resources"]["memory"] == "7Gi"
    assert session["namespaces"]["budget"] == "large"
    assert session["namespaces"]["role"] == "view"
    assert session["namespaces"]["security"] == {"policy": "restricted", "token": {"enabled": False}}
    assert "registry" not in session["applications"]
    assert "registry-deployment-s-joe" in resources
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
    assert containers[0]["image"] == env["data"]["images"]["packageR"]
    assert deployment["spec"]["template"]["spec"]["containers"][0]["image"] == env["data"]["images"]["packageR"]
    assert manifest(resources, "registry-deployment-s-joe")["spec"]["template"]["spec"]["containers"][0]["image"] == env["data"]["images"]["registry"]
    assert manifest(resources, "data-s3-deployment-s-joe")["spec"]["template"]["spec"]["containers"][0]["image"] == env["data"]["images"]["rclone"]
    for key in ("data-deployment-s-joe", "data-s3-deployment-s-joe"):
        service_containers = manifest(resources, key)["spec"]["template"]["spec"]["containers"]
        assert next(c["image"] for c in service_containers if c["name"] == "oauth2-proxy") == env["data"]["images"]["oauth2Proxy"]
    assert next(c["image"] for c in service_containers if c["name"] == "gateway") == "nginxinc/nginx-unprivileged:1.28-alpine"
    assert not any("--perm.create=true" in arg for container in containers for arg in container.get("args", []))
    session = manifest(resources, "workshopsession-s-joe-default")
    assert any(entry["name"] == "KUBECONFIG" for entry in session["spec"]["session"]["env"])
    print("PASS environment image, session, security, storage, and quota settings", flush=True)

    env["data"]["defaults"]["vcluster"] = {"enabled": False}
    env["data"]["defaults"]["data"]["readOnlyMount"] = False
    source["spec"]["vcluster"] = {"enabled": True}
    source["spec"]["data"]["readOnlyMount"] = True
    resources = render(args, env, source, observed)
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
    resources = render(args, env, source, observed)
    for name in ("data-deployment-s-joe", "observe-runtime-storage-secret-s-joe"):
        assert name not in resources
    workshop = manifest(resources, "workshop-s-joe")["spec"]
    assert "registry" not in workshop["session"]["applications"]
    assert "registry-deployment-s-joe" not in resources
    assert not any(dashboard["name"] == "Data" for dashboard in workshop["session"]["dashboards"])
    print("PASS environment Data and registry toggles", flush=True)


if __name__ == "__main__":
    main()
