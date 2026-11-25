#!/usr/bin/env python3
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Request a cold PostgreSQL snapshot and retain completed recovery points."""

import argparse
import json
from pathlib import Path
import ssl
import time
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

LABEL = "datalabs.versioneer.at/postgres-backup"
SOURCE = "datalabs.versioneer.at/source-cluster-uid"


class API:
    def __init__(self):
        account = Path("/var/run/secrets/kubernetes.io/serviceaccount")
        self.token = account / "token"
        self.context = ssl.create_default_context(cafile=str(account / "ca.crt"))

    def call(self, method, path, body=None):
        request = Request(
            "https://kubernetes.default.svc" + path,
            data=None if body is None else json.dumps(body).encode(), method=method,
            headers={"Authorization": "Bearer " + self.token.read_text().strip(),
                     "Content-Type": "application/json"},
        )
        with urlopen(request, context=self.context, timeout=30) as result:
            return json.load(result)


def backup(api, namespace, cluster_name, snapshot_class, retention, timeout=600):
    namespace = quote(namespace, safe="")
    path = "/apis/postgresql.cnpg.io/v1/namespaces/" + namespace
    cluster_path = path + "/clusters/" + quote(cluster_name, safe="")
    path += "/backups"
    snapshot_path = "/apis/snapshot.storage.k8s.io/v1/namespaces/" + namespace + "/volumesnapshots/"
    selected_class = api.call("GET", "/apis/snapshot.storage.k8s.io/v1/volumesnapshotclasses/" + quote(snapshot_class, safe=""))
    if selected_class.get("deletionPolicy") != "Delete":
        raise RuntimeError("PostgreSQL snapshot retention requires deletion policy Delete.")
    cluster = api.call("GET", cluster_path)
    settings = cluster.get("spec", {}).get("backup", {}).get("volumeSnapshot", {})
    if (cluster["metadata"].get("deletionTimestamp") or settings.get("className") != snapshot_class
            or settings.get("online") is not False or settings.get("snapshotOwnerReference") != "backup"):
        raise RuntimeError("The cluster must use cold snapshots owned by their Backup resources.")
    uid = cluster["metadata"]["uid"]
    selector = urlencode({"labelSelector": f"{LABEL}={cluster_name},{SOURCE}={uid}"})

    def owned_backups():
        return [item for item in api.call("GET", path + "?" + selector)["items"]
                if item["metadata"].get("labels", {}).get(LABEL) == cluster_name
                and item["metadata"]["labels"].get(SOURCE) == uid
                and item.get("spec", {}).get("cluster", {}).get("name") == cluster_name
                and item["spec"].get("method") == "volumeSnapshot"
                and item["spec"].get("online") is False
                and not item["metadata"].get("deletionTimestamp")]

    def ready(item):
        if item.get("status", {}).get("phase") != "completed":
            return False
        elements = item["status"].get("snapshotBackupStatus", {}).get("elements") or []
        if not elements or not any(element.get("type") == "PG_DATA" for element in elements):
            return False
        for element in elements:
            snapshot = api.call("GET", snapshot_path + quote(element["name"], safe=""))
            if (snapshot["metadata"].get("deletionTimestamp")
                    or snapshot.get("status", {}).get("readyToUse") is not True
                    or snapshot.get("status", {}).get("error")
                    or not any(owner.get("kind") == "Backup" and owner.get("uid") == item["metadata"]["uid"]
                               for owner in snapshot["metadata"].get("ownerReferences", []))):
                return False
        return True

    pending = [item for item in owned_backups() if item.get("status", {}).get("phase") not in ("completed", "failed")]
    if len(pending) > 1:
        raise RuntimeError("Multiple pending PostgreSQL backups need operator review.")
    current = pending[0] if pending else api.call("POST", path, {
        "apiVersion": "postgresql.cnpg.io/v1", "kind": "Backup",
        "metadata": {"generateName": "snapshot-" + cluster_name[:40] + "-",
                     "labels": {LABEL: cluster_name, SOURCE: uid}},
        "spec": {"cluster": {"name": cluster_name}, "method": "volumeSnapshot",
                 "online": False, "target": "primary"},
    })
    backup_name = current["metadata"]["name"]
    deadline = time.monotonic() + timeout
    while True:
        current = api.call("GET", path + "/" + quote(backup_name, safe=""))
        if current.get("status", {}).get("phase") == "failed":
            raise RuntimeError("CloudNativePG reported a failed snapshot backup.")
        if ready(current):
            break
        if time.monotonic() >= deadline:
            raise RuntimeError("The PostgreSQL snapshot did not complete before the deadline.")
        time.sleep(3)
    if api.call("GET", cluster_path)["metadata"]["uid"] != uid:
        raise RuntimeError("The PostgreSQL cluster changed while the backup was being taken.")
    backups = owned_backups()
    completed = sorted((item for item in backups if ready(item)),
                       key=lambda item: (item["metadata"]["creationTimestamp"], item["metadata"]["name"]), reverse=True)
    expired = completed[retention:]
    expired += [item for item in backups if item.get("status", {}).get("phase") == "failed"]
    # Remove old backups only after a new recovery point and its snapshots are ready.
    for item in expired:
        metadata = item["metadata"]
        preconditions = {"uid": metadata["uid"]}
        if metadata.get("resourceVersion"):
            preconditions["resourceVersion"] = metadata["resourceVersion"]
        api.call("DELETE", path + "/" + quote(metadata["name"], safe=""),
                 {"apiVersion": "v1", "kind": "DeleteOptions", "preconditions": preconditions})
    print("PostgreSQL snapshot backup is ready: " + backup_name, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("namespace")
    parser.add_argument("cluster")
    parser.add_argument("snapshot_class")
    parser.add_argument("retention", type=int)
    args = parser.parse_args()
    if not 1 <= args.retention <= 100:
        parser.error("retention must be from 1 to 100")
    backup(API(), args.namespace, args.cluster, args.snapshot_class, args.retention)


if __name__ == "__main__":
    main()
