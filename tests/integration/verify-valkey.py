#!/usr/bin/env python3
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Check Valkey CSI capture, retention, RDB recovery, and backup disablement."""

import argparse
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import time

import yaml


NAMESPACE = "verify-valkey"


def wait(check, message, seconds=900):
    deadline = time.monotonic() + seconds
    next_report = time.monotonic() + 30
    while True:
        result = check()
        if result:
            return result
        now = time.monotonic()
        assert now < deadline, message
        if now >= next_report:
            print("Waiting: " + message, flush=True)
            next_report = now + 30
        time.sleep(3)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("kubeconfig", "context", "image", "value", "prefix", "other-prefix"):
        parser.add_argument("--" + field, required=True)
    args = parser.parse_args()
    command = ["kubectl", "--kubeconfig", args.kubeconfig, "--context", args.context]

    def kube(*values, body=None, namespace=NAMESPACE, timeout=60):
        result = subprocess.run([*command, "--namespace", namespace, *values],
                                input=json.dumps(body) if body is not None else None,
                                text=True, capture_output=True, timeout=timeout)
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    def get(resource):
        value = kube("get", resource, "--ignore-not-found", "-o", "json")
        return json.loads(value) if value else None

    def create(body):
        return json.loads(kube("create", "-f", "-", "-o", "json", body=body))

    def delete(resource):
        kube("delete", resource, "--ignore-not-found", "--wait=false")
        wait(lambda: get(resource) is None, "Resource deletion: " + resource)

    cronjob = wait(lambda: (job if (job := get("cronjob/valkey-verify-backup"))
                           and not job["spec"].get("suspend") else None), "Valkey snapshot schedule needs its data PVC")
    claim = cronjob["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]["args"][2]
    source = get("pvc/" + claim)
    uid = source["metadata"]["uid"]
    storage_class = get("storageclass/" + source["spec"]["storageClassName"])
    if storage_class.get("allowVolumeExpansion"):
        workload = get("statefulset/verify")["spec"]
        kube("patch", "datalab/verify-valkey", "--type=merge", "--patch",
             json.dumps({"spec": {"stores": {"verify": {"storage": "2Gi"}}}}), namespace="workspace")
        source = wait(lambda: (pvc if (pvc := get("pvc/" + claim)).get("status", {}).get("capacity", {}).get("storage") == "2Gi" else None),
                      "Valkey data PVC expansion")
        assert source["metadata"]["uid"] == uid
        assert get("statefulset/verify")["spec"] == workload
        print("PASS Valkey storage expansion keeps the data PVC and StatefulSet configuration", flush=True)
    else:
        print("SKIPPED Valkey storage expansion: the StorageClass does not allow expansion", flush=True)

    def snapshots():
        return [item for item in json.loads(kube("get", "volumesnapshots.snapshot.storage.k8s.io", "-o", "json"))["items"]
                if item["metadata"].get("labels", {}).get("datalabs.versioneer.at/valkey") == "verify"
                and item["metadata"]["labels"].get("datalabs.versioneer.at/source-pvc-uid") == uid
                and item["spec"]["source"].get("persistentVolumeClaimName") == claim]

    def backup(count, failed=False):
        previous = {item["metadata"]["uid"] for item in snapshots()}
        document = deepcopy(cronjob["spec"]["jobTemplate"])
        document.update(apiVersion="batch/v1", kind="Job", metadata={"generateName": "test-valkey-backup-"})
        if failed:
            document["spec"]["backoffLimit"] = 0
            document["spec"]["template"]["spec"]["containers"][0]["args"][3] = "test-missing-snapshot-class"
        job = create(document)
        resource = "job/" + job["metadata"]["name"]

        def finished():
            conditions = get(resource).get("status", {}).get("conditions", [])
            error = any(c["type"] == "Failed" and c["status"] == "True" for c in conditions)
            complete = any(c["type"] == "Complete" and c["status"] == "True" for c in conditions)
            assert not (error and not failed), "Valkey snapshot Job failed"
            assert not (complete and failed), "Valkey accepted a missing snapshot class"
            return error if failed else complete

        try:
            wait(finished, "Valkey backup Job completion")
        except Exception:
            print(kube("describe", resource), flush=True)
            print(kube("logs", resource), flush=True)
            raise
        delete(resource)
        if failed:
            assert {item["metadata"]["uid"] for item in snapshots()} == previous
            return None

        def retained():
            values = snapshots()
            if len(values) == count and all(item.get("status", {}).get("readyToUse") is True
                                           and item["metadata"]["labels"].get("datalabs.versioneer.at/valkey-snapshot-verified") == "true"
                                           and not item["metadata"].get("deletionTimestamp") for item in values):
                return next((item for item in values if item["metadata"]["uid"] not in previous), None)
            return None
        return wait(retained, "Valkey snapshot readiness and retention")

    first = backup(1)
    backup(0, failed=True)
    backup(2)
    recovery = backup(2)
    assert get("volumesnapshot/" + first["metadata"]["name"]) is None
    print("PASS Valkey CSI retention keeps two recovery points and preserves them after a failed backup", flush=True)

    create({"apiVersion": "v1", "kind": "PersistentVolumeClaim",
            "metadata": {"name": "test-valkey-recovery"},
            "spec": {"accessModes": ["ReadWriteOnce"], "storageClassName": source["spec"]["storageClassName"],
                     "resources": {"requests": {"storage": recovery["status"].get("restoreSize") or source["status"]["capacity"]["storage"]}},
                     "dataSource": {"apiGroup": "snapshot.storage.k8s.io", "kind": "VolumeSnapshot",
                                    "name": recovery["metadata"]["name"]}}})
    template = (Path(__file__).parent / "manifests/valkey/restore.yaml").read_text()
    for name, value in {"PROBE_NAME": "test-valkey-recovery", "STORE_NAMESPACE": NAMESPACE,
                        "CLIENT_IMAGE": args.image, "PROBE_VALUE": args.value,
                        "KEY_PREFIX": args.prefix, "OTHER_KEY_PREFIX": args.other_prefix}.items():
        template = template.replace("__" + name + "__", value)
    create(yaml.safe_load(template))

    def restored():
        phase = get("pod/test-valkey-recovery").get("status", {}).get("phase")
        assert phase != "Failed", "Valkey recovery probe failed"
        return phase == "Succeeded"

    try:
        wait(restored, "Valkey recovery and AOF restart")
    except Exception:
        print(kube("describe", "pod/test-valkey-recovery"), flush=True)
        print(kube("logs", "pod/test-valkey-recovery"), flush=True)
        raise
    print(kube("logs", "pod/test-valkey-recovery"), flush=True)
    delete("pod/test-valkey-recovery")
    delete("pvc/test-valkey-recovery")

    points = {item["metadata"]["uid"] for item in snapshots()}
    previous = get("statefulset/verify")["spec"]["template"]["metadata"]["annotations"]["datalabs.versioneer.at/valkey-acl-checksum"]
    kube("patch", "datalab/verify-valkey", "--type=merge", "--patch",
         json.dumps({"spec": {"stores": {"verify": {"backups": False}}}}), namespace="workspace")
    wait(lambda: get("cronjob/valkey-verify-backup") is None, "Valkey backup schedule removal")
    wait(lambda: get("statefulset/verify")["spec"]["template"]["metadata"]["annotations"]["datalabs.versioneer.at/valkey-acl-checksum"] != previous,
         "Valkey backup ACL removal")
    kube("rollout", "status", "statefulset/verify", "--timeout=5m", timeout=330)
    assert get("pvc/" + claim)["metadata"]["uid"] == uid
    assert {item["metadata"]["uid"] for item in snapshots()} == points
    for prefix, expected in ((args.prefix, args.value), (args.other_prefix, args.value + "-other")):
        value = kube("exec", "pod/verify-0", "--", "valkey-cli", "--raw", "GET",
                     prefix + "provider-datalab:verify").strip()
        assert value == expected, "The Valkey rollout lost stored data"
    print("PASS disabling Valkey backups keeps the data PVC and completed snapshots", flush=True)


if __name__ == "__main__":
    main()
