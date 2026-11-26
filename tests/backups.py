#!/usr/bin/env python3
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Check snapshot enablement and Valkey backup settings."""

import base64
from copy import deepcopy
from pathlib import Path

import yaml

from render import arguments, load, manifest, render


def main():
    args = arguments()
    original = load("examples/base/002-lab.yaml")
    environments = list(yaml.safe_load_all(Path("tests/environmentconfig.yaml").read_text()))
    environment = next(item for item in environments if item["metadata"]["name"] == "datalab")
    for enabled in (None, False, True):
        source = deepcopy(original)
        for config in source["spec"]["stores"].values():
            if enabled is None:
                config.pop("backups", None)
            else:
                config["backups"] = enabled
        resources = render(args, environment, source, "tests/observed/002-lab.yaml")
        active = enabled is True
        cluster = manifest(resources, "db-cluster-s-jeff-pg0")
        assert ("backup" in cluster["spec"]) == active
        if active:
            assert cluster["spec"]["backup"]["volumeSnapshot"]["online"] is False
            assert cluster["spec"]["backup"]["volumeSnapshot"]["snapshotOwnerReference"] == "backup"
        schedules = [body["spec"]["forProvider"]["manifest"] for body in resources.values()
                     if body.get("kind") == "Object"
                     and body["spec"]["forProvider"]["manifest"].get("kind") == "CronJob"]
        assert any(job["metadata"]["name"] == "postgres-snapshot-pg0" for job in schedules) == active
        acl = base64.b64decode(manifest(resources, "valkey-acl-secret-s-jeff-cache")["data"]["user.acl"]).decode()
        assert ("user backup " in acl) == active
        assert ("valkey-backup-cronjob-s-jeff-cache" in resources) == active
        claims = [body["spec"]["forProvider"]["manifest"]["metadata"]["name"] for body in resources.values()
                  if body.get("spec", {}).get("forProvider", {}).get("manifest", {}).get("kind") == "PersistentVolumeClaim"]
        assert claims == [manifest(resources, "valkey-data-s-jeff-cache")["metadata"]["name"]]
        if active:
            assert "-@all +ping +info +bgsave +client|pause +client|unpause" in acl
            job = manifest(resources, "valkey-backup-cronjob-s-jeff-cache")
            assert job["spec"]["suspend"] is True, "Wait for the data PVC before scheduling"
            pod = job["spec"]["jobTemplate"]["spec"]["template"]["spec"]
            assert not any("persistentVolumeClaim" in volume for volume in pod["volumes"])
        print(f"PASS PostgreSQL and Valkey backups={enabled}: CSI schedules need no backup PVC", flush=True)

    observed = list(yaml.safe_load_all(Path("tests/observed/002-lab.yaml").read_text()))
    observed.append({"apiVersion": "kubernetes.m.crossplane.io/v1alpha1", "kind": "Object",
                     "metadata": {"name": "valkey-pod-s-jeff-cache",
                                  "annotations": {"crossplane.io/composition-resource-name": "valkey-pod-s-jeff-cache"}},
                     "status": {"atProvider": {"manifest": {
                         "apiVersion": "v1", "kind": "Pod", "metadata": {"name": "cache-0", "namespace": "s-jeff"},
                         "spec": {"volumes": [{"name": "data", "persistentVolumeClaim": {"claimName": "data-cache-0"}}],
                                  "containers": [{"volumeMounts": [{"name": "data", "mountPath": "/data"}]}]},
                     }}}})
    ready = render(args, environment, original, observed)
    assert manifest(ready, "valkey-backup-cronjob-s-jeff-cache")["spec"]["suspend"] is False
    policy = manifest(ready, "valkey-backup-network-s-jeff-cache")["spec"]
    selector = policy["egress"][0]["to"][0]["podSelector"]["matchLabels"]
    labels = manifest(ready, "valkey-cache-s-jeff-cache")["spec"]["template"]["metadata"]["labels"]
    assert selector and all(labels.get(key) == value for key, value in selector.items())
    rules = manifest(ready, "valkey-backup-role-s-jeff-cache")["rules"]
    assert rules[:2] == [
        {"apiGroups": [""], "resources": ["persistentvolumeclaims"], "resourceNames": ["data-cache-0"], "verbs": ["get"]},
        {"apiGroups": [""], "resources": ["pods"], "resourceNames": ["cache-0"], "verbs": ["get"]},
    ]
    print("PASS Valkey schedules use the observed data PVC and restrict Pod and PVC reads by name", flush=True)

    for value in (0, 101, True, 1.5, "2"):
        invalid = deepcopy(environment)
        invalid["data"]["cacheStore"]["maxSnapshots"] = value
        render(args, invalid, original, "tests/observed/002-lab.yaml", error="data.cacheStore.maxSnapshots must be an integer")
    invalid = deepcopy(environment)
    invalid["data"].pop("volumes", None)
    invalid["data"]["database"].pop("snapshotClassName", None)
    invalid["data"]["cacheStore"].pop("snapshotClassName", None)
    valkey_only = deepcopy(original)
    valkey_only["spec"]["stores"]["pg0"]["backups"] = False
    render(args, invalid, valkey_only, "tests/observed/002-lab.yaml", error="Valkey backups require")
    print("PASS Valkey rejects invalid retention and missing snapshot configuration", flush=True)


if __name__ == "__main__":
    main()
