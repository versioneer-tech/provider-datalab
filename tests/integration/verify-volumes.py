#!/usr/bin/env python3
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Check host PVC data, snapshot recovery, retention, and Datalab status."""

import argparse
from copy import deepcopy
import json
import subprocess
import time

NAMESPACE = "verify-volumes"
LABEL = "datalabs.versioneer.at/volume"
SOURCE = "datalabs.versioneer.at/source-pvc-uid"


def wait_for(check, message, seconds=600):
    deadline = time.monotonic() + seconds
    while True:
        value = check()
        if value:
            return value
        assert time.monotonic() < deadline, message
        time.sleep(3)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kubeconfig", required=True)
    parser.add_argument("--context", required=True)
    parser.add_argument("--snapshot-class", required=True)
    args = parser.parse_args()
    command = ["kubectl", "--kubeconfig", args.kubeconfig, "--context", args.context]

    def kube(*values, body=None, namespace=NAMESPACE, timeout=60):
        result = subprocess.run(
            [*command, "--namespace", namespace, *values],
            input=json.dumps(body) if body is not None else None,
            text=True, capture_output=True, timeout=timeout,
        )
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    def get(resource):
        value = kube("get", resource, "--ignore-not-found", "-o", "json")
        return json.loads(value) if value else None

    def present(resource):
        return wait_for(lambda: get(resource), "Resource not created: " + resource)

    def create(document):
        return json.loads(kube("create", "-f", "-", "-o", "json", body=document))

    def diagnose(resource, logs=False):
        commands = [("describe", resource)]
        if logs:
            commands.append(("logs", resource, "--all-containers=true"))
        for values in commands:
            try:
                print(kube(*values), flush=True)
            except (AssertionError, subprocess.TimeoutExpired):
                pass

    def delete(resource):
        kube("delete", resource, "--ignore-not-found", "--wait=false")
        wait_for(lambda: get(resource) is None, "Resource not deleted: " + resource)

    def volumes(values):
        kube("patch", "datalab/verify-volumes", "--type=merge", "--patch",
             json.dumps({"spec": {"volumes": values}}), namespace="workspace")

    def datalab():
        return json.loads(kube("get", "datalab/verify-volumes", "-o", "json", namespace="workspace"))

    def status(count):
        def current():
            lab = datalab()
            entries = lab.get("status", {}).get("volumes", [])
            entry = next((entry for entry in entries if entry["name"] == "analysis"), {})
            backup = entry.get("backup", {})
            return entry if backup.get("readySnapshots") == count else None
        return wait_for(current, "Snapshot count did not reach Datalab status")

    def probe(name, script):
        pod = create({
            "apiVersion": "v1", "kind": "Pod", "metadata": {"generateName": "test-volume-"},
            "spec": {
                "restartPolicy": "Never", "automountServiceAccountToken": False,
                "securityContext": {"runAsNonRoot": True, "runAsUser": 1000, "runAsGroup": 1000,
                                    "fsGroup": 1000, "seccompProfile": {"type": "RuntimeDefault"}},
                "containers": [{
                    "name": "probe", "image": "busybox:1.36.1", "command": ["sh", "-ec", script],
                    "securityContext": {"allowPrivilegeEscalation": False, "capabilities": {"drop": ["ALL"]}},
                    "resources": {"requests": {"cpu": "10m", "memory": "16Mi", "ephemeral-storage": "1Mi"},
                                  "limits": {"cpu": "100m", "memory": "64Mi", "ephemeral-storage": "32Mi"}},
                    "volumeMounts": [{"name": "data", "mountPath": "/data"}],
                }],
                "volumes": [{"name": "data", "persistentVolumeClaim": {"claimName": "volume-" + name}}],
            },
        })
        resource = "pod/" + pod["metadata"]["name"]
        claim = "pvc/volume-" + name

        def finished():
            phase = get(resource).get("status", {}).get("phase")
            assert phase != "Failed", "Volume file probe failed: " + resource
            return phase == "Succeeded"

        try:
            wait_for(lambda: get(claim).get("status", {}).get("phase") == "Bound",
                     "Volume did not bind after its consumer Pod was created: " + claim, seconds=300)
            kube("wait", resource, "--for=condition=PodScheduled", "--timeout=90s", timeout=105)
            wait_for(finished, "Volume file probe did not finish: " + resource, seconds=300)
            output = kube("logs", resource)
        except (AssertionError, subprocess.TimeoutExpired):
            diagnose(claim)
            diagnose(resource, logs=True)
            raise
        delete(resource)
        return output

    def snapshots():
        return json.loads(kube("get", "volumesnapshots", "-o", "json"))["items"]

    present("pvc/volume-analysis")
    probe("analysis", "printf before-backup > /data/marker; sync")
    source = get("pvc/volume-analysis")
    uid = source["metadata"]["uid"]
    assert source["status"]["phase"] == "Bound"
    assert not source["metadata"].get("ownerReferences")
    wait_for(lambda: any(condition.get("type") == "Ready" and condition.get("status") == "True"
                         for condition in datalab().get("status", {}).get("conditions", [])),
             "The volume Datalab did not become Ready after its PVC was bound")
    print("PASS volume Datalab readiness after PVC binding", flush=True)

    def owned():
        return [item for item in snapshots()
                if item["metadata"].get("labels", {}).get(LABEL) == "analysis"
                and item["metadata"]["labels"].get(SOURCE) == uid
                and item["spec"]["source"].get("persistentVolumeClaimName") == "volume-analysis"]

    cronjob = present("cronjob/volume-snapshot-analysis")

    def backup(fail=False):
        job = deepcopy(cronjob["spec"]["jobTemplate"])
        job.update(apiVersion="batch/v1", kind="Job", metadata={"generateName": "test-volume-backup-"})
        if fail:
            job["spec"]["backoffLimit"] = 0
            job["spec"]["template"]["spec"]["containers"][0]["args"][3] = "test-missing-snapshot-class"
        job = create(job)
        name = job["metadata"]["name"]

        def finished():
            conditions = get("job/" + name).get("status", {}).get("conditions", [])
            failed = any(item["type"] == "Failed" and item["status"] == "True" for item in conditions)
            complete = any(item["type"] == "Complete" and item["status"] == "True" for item in conditions)
            assert not (failed and not fail), "Backup Job failed: " + name
            assert not (complete and fail), "Backup accepted a missing snapshot class"
            return failed if fail else complete

        try:
            pod = wait_for(lambda: json.loads(kube("get", "pods", "--selector", "batch.kubernetes.io/job-name=" + name,
                                                   "-o", "json"))["items"], "Backup Job did not create a Pod", seconds=90)[0]
            kube("wait", "pod/" + pod["metadata"]["name"], "--for=condition=PodScheduled", "--timeout=90s", timeout=105)
            wait_for(finished, "Backup Job did not finish: " + name, seconds=900)
        except (AssertionError, subprocess.TimeoutExpired):
            diagnose("job/" + name, logs=True)
            raise
        delete("job/" + name)
        return owned()

    first = backup()
    assert len(first) == 1 and first[0]["status"]["readyToUse"] is True
    foreign = create({
        "apiVersion": "snapshot.storage.k8s.io/v1", "kind": "VolumeSnapshot",
        "metadata": {"generateName": "test-unrelated-", "labels": {LABEL: "analysis", SOURCE: "test-other-pvc-uid"}},
        "spec": {"volumeSnapshotClassName": args.snapshot_class, "source": {"persistentVolumeClaimName": "volume-analysis"}},
    })
    wait_for(lambda: get("volumesnapshot/" + foreign["metadata"]["name"]).get("status", {}).get("readyToUse"),
             "Unrelated snapshot did not become ready")
    incomplete = create({
        "apiVersion": "snapshot.storage.k8s.io/v1", "kind": "VolumeSnapshot",
        "metadata": {"generateName": "test-incomplete-", "labels": {LABEL: "analysis", SOURCE: uid}},
        "spec": {"volumeSnapshotClassName": "test-missing-snapshot-class", "source": {"persistentVolumeClaimName": "volume-analysis"}},
    })
    backup(fail=True)
    assert get("volumesnapshot/" + first[0]["metadata"]["name"])["status"]["readyToUse"] is True
    probe("analysis", "printf second-backup > /data/marker; sync")
    second = backup()
    assert len(second) == 2
    wait_for(lambda: get("volumesnapshot/" + incomplete["metadata"]["name"]) is None, "Incomplete snapshot was not removed")
    probe("analysis", "printf snapshot-value > /data/marker; sync")
    latest = backup()
    assert len(latest) == 2 and all(item["status"]["readyToUse"] is True for item in latest)
    wait_for(lambda: get("volumesnapshot/" + first[0]["metadata"]["name"]) is None, "Oldest recovery point was not pruned")
    assert get("volumesnapshot/" + foreign["metadata"]["name"])["metadata"]["uid"] == foreign["metadata"]["uid"]
    recovery = next(item for item in latest if item["metadata"]["uid"] not in {item["metadata"]["uid"] for item in second})
    restore_storage = recovery["status"].get("restoreSize") or source["status"]["capacity"]["storage"]
    entry = status(2)
    assert entry["pvcRef"] == {"namespace": NAMESPACE, "name": "volume-analysis"}
    assert entry["phase"] == "Bound"
    assert entry["backup"]["lastSuccessfulTime"] == recovery["status"]["creationTime"]
    print("PASS snapshot Jobs, two-snapshot default, failure cleanup, source UID isolation, and observed backup status", flush=True)

    probe("analysis", "printf after-backup > /data/marker; sync")
    volumes({"recovered": {"storage": restore_storage, "restoreFrom": recovery["metadata"]["name"]}})
    present("pvc/volume-recovered")
    present("cronjob/volume-snapshot-recovered")
    assert probe("recovered", "cat /data/marker") == "snapshot-value"
    probe("recovered", "printf restored-only > /data/marker; sync")
    assert probe("analysis", "cat /data/marker") == "after-backup"
    assert get("pvc/volume-analysis")["metadata"]["uid"] == uid
    volumes({"recovered": None})
    wait_for(lambda: get("pvc/volume-recovered") is None and get("cronjob/volume-snapshot-recovered") is None
             and get("serviceaccount/volume-snapshot-recovered") is None, "Restored volume removal did not finish")
    assert get("cronjob/volume-snapshot-analysis") is not None
    assert get("pvc/volume-analysis")["metadata"]["uid"] == uid
    assert status(2)["backup"] == entry["backup"]
    print("PASS restore preserves snapshot contents; writes and backup schedules remain independent", flush=True)

    retained = {item["metadata"]["uid"] for item in snapshots()}
    volumes({"analysis": None})
    wait_for(lambda: get("pvc/volume-analysis") is None and get("cronjob/volume-snapshot-analysis") is None
             and get("serviceaccount/volume-snapshot-analysis") is None, "Source volume removal did not finish")
    assert {item["metadata"]["uid"] for item in snapshots()} == retained
    volumes({"recovered": {"storage": restore_storage, "restoreFrom": recovery["metadata"]["name"]}})
    present("pvc/volume-recovered")
    assert probe("recovered", "cat /data/marker") == "snapshot-value"
    volumes({"recovered": None})
    wait_for(lambda: get("pvc/volume-recovered") is None, "Recovered PVC was not deleted")
    print("PASS completed snapshots remain usable after the source volume is removed", flush=True)


if __name__ == "__main__":
    main()
