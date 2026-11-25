#!/usr/bin/env python3
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Create a volume snapshot and prune older completed snapshots."""

import argparse
import json
from pathlib import Path
import ssl
import time
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

LABEL = "datalabs.versioneer.at/volume"
SOURCE = "datalabs.versioneer.at/source-pvc-uid"


class API:
    def __init__(self):
        account = Path("/var/run/secrets/kubernetes.io/serviceaccount")
        self.token = account / "token"
        self.context = ssl.create_default_context(cafile=str(account / "ca.crt"))

    def call(self, method, path, body=None):
        request = Request(
            "https://kubernetes.default.svc" + path,
            data=None if body is None else json.dumps(body).encode(),
            method=method,
            headers={"Authorization": "Bearer " + self.token.read_text().strip(),
                     "Content-Type": "application/merge-patch+json" if method == "PATCH" else "application/json"},
        )
        with urlopen(request, context=self.context, timeout=30) as result:
            return json.load(result)


def backup(api, namespace, volume, claim, snapshot_class, retention, timeout=600,
           label=LABEL, prepare=None, validate=None, verified_label=None):
    core = "/api/v1/namespaces/" + quote(namespace, safe="")
    path = "/apis/snapshot.storage.k8s.io/v1/namespaces/" + quote(namespace, safe="") + "/volumesnapshots"
    volume_class = api.call("GET", "/apis/snapshot.storage.k8s.io/v1/volumesnapshotclasses/" + quote(snapshot_class, safe=""))
    if volume_class.get("deletionPolicy") != "Delete":
        raise RuntimeError("The snapshot class must use deletion policy Delete for retention.")
    pvc = api.call("GET", core + "/persistentvolumeclaims/" + quote(claim, safe=""))
    if pvc.get("status", {}).get("phase") != "Bound" or pvc["metadata"].get("deletionTimestamp"):
        raise RuntimeError("The source PVC must be bound and must not be deleting.")
    uid = pvc["metadata"]["uid"]
    selector = urlencode({"labelSelector": f"{label}={volume},{SOURCE}={uid}"})

    def owned_snapshots():
        return [item for item in api.call("GET", path + "?" + selector)["items"]
                if item["metadata"].get("labels", {}).get(label) == volume
                and item["metadata"].get("labels", {}).get(SOURCE) == uid
                and item.get("spec", {}).get("source", {}).get("persistentVolumeClaimName") == claim]

    def remove(item):
        metadata = item["metadata"]
        preconditions = {"uid": metadata["uid"]}
        if metadata.get("resourceVersion"):
            preconditions["resourceVersion"] = metadata["resourceVersion"]
        api.call("DELETE", path + "/" + quote(metadata["name"], safe=""),
                 {"apiVersion": "v1", "kind": "DeleteOptions", "preconditions": preconditions})

    snapshots = owned_snapshots()
    def verified(item):
        return not verified_label or item["metadata"].get("labels", {}).get(verified_label) == "true"

    incomplete = [item for item in snapshots
                  if item.get("status", {}).get("readyToUse") is not True or not verified(item)]
    for item in incomplete:
        if not item["metadata"].get("deletionTimestamp"):
            remove(item)
    if incomplete:
        snapshots = owned_snapshots()
    # A stopped Job can leave a snapshot behind. Finish cleanup before allocating another.
    if any(item["metadata"].get("deletionTimestamp")
           or item.get("status", {}).get("readyToUse") is not True or not verified(item) for item in snapshots):
        raise RuntimeError("Waiting for previous snapshot cleanup before creating another backup.")

    if prepare:
        prepare()
    created = api.call("POST", path, {
        "apiVersion": "snapshot.storage.k8s.io/v1", "kind": "VolumeSnapshot",
        "metadata": {"generateName": ("volume-" if label == LABEL else "redis-") + volume + "-",
                     "labels": {label: volume, SOURCE: uid}},
        "spec": {"volumeSnapshotClassName": snapshot_class,
                 "source": {"persistentVolumeClaimName": claim}},
    })
    name = created["metadata"]["name"]
    deadline = time.monotonic() + timeout
    while True:
        current = api.call("GET", path + "/" + quote(name, safe=""))
        state = current.get("status", {})
        if state.get("error"):
            raise RuntimeError("The CSI driver reported a snapshot error.")
        if state.get("readyToUse") is True:
            break
        if time.monotonic() >= deadline:
            raise RuntimeError("The volume snapshot did not become ready before the deadline.")
        time.sleep(3)

    source = api.call("GET", core + "/persistentvolumeclaims/" + quote(claim, safe=""))
    if source["metadata"]["uid"] != uid:
        raise RuntimeError("The source PVC changed while the snapshot was being taken.")

    if validate:
        try:
            validate()
        except Exception:
            # Do not retain a capture made after the write pause expired or the server changed.
            remove(current)
            raise

    if verified_label:
        metadata = current["metadata"]
        api.call("PATCH", path + "/" + quote(name, safe=""), {"metadata": {
            "uid": metadata["uid"], "resourceVersion": metadata["resourceVersion"],
            "labels": {verified_label: "true"},
        }})

    completed = sorted(
        (item for item in owned_snapshots()
         if item.get("status", {}).get("readyToUse") is True
         and verified(item)
         and not item["metadata"].get("deletionTimestamp")),
        key=lambda item: (item["metadata"]["creationTimestamp"], item["metadata"]["name"]),
        reverse=True,
    )
    # A failed or incomplete backup must not remove a usable recovery point.
    for item in completed[retention:]:
        remove(item)
    print("Volume snapshot is ready: " + name, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("namespace")
    parser.add_argument("volume")
    parser.add_argument("claim")
    parser.add_argument("snapshot_class")
    parser.add_argument("retention", type=int)
    args = parser.parse_args()
    if args.retention < 1:
        parser.error("retention must be at least one")
    backup(API(), args.namespace, args.volume, args.claim, args.snapshot_class, args.retention)


if __name__ == "__main__":
    main()
