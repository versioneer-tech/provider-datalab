#!/usr/bin/env python3
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Save Valkey data and capture its PVC during a bounded write pause."""

import argparse
from contextlib import closing
from pathlib import Path
import runpy
import socket
import time
from urllib.parse import quote

snapshots = runpy.run_path(str(Path(__file__).with_name("volume-snapshot.py")))
LABEL = "datalabs.versioneer.at/valkey"
VERIFIED = "datalabs.versioneer.at/valkey-snapshot-verified"


class Valkey:
    def __init__(self, host, password):
        self.socket = socket.create_connection((host, 6379), timeout=60)
        self.stream = self.socket.makefile("rb")
        self.command("AUTH", "backup", password)

    def close(self):
        self.stream.close()
        self.socket.close()

    def command(self, *arguments):
        values = [str(value).encode() for value in arguments]
        self.socket.sendall(b"*%d\r\n" % len(values) + b"".join(
            b"$%d\r\n" % len(value) + value + b"\r\n" for value in values))
        line = self.stream.readline()
        if not line.endswith(b"\r\n"):
            raise RuntimeError("Valkey closed the backup connection.")
        kind, value = line[:1], line[1:-2]
        if kind == b"+":
            return value.decode()
        if kind == b"$" and int(value) >= 0:
            data = self.stream.read(int(value) + 2)
            if len(data) != int(value) + 2 or not data.endswith(b"\r\n"):
                raise RuntimeError("Valkey returned an incomplete response.")
            return data[:-2].decode()
        # Server errors can contain command arguments; do not put them in Job logs.
        raise RuntimeError("Valkey rejected the backup command.")


def capture(api, valkey, namespace, store, claim, snapshot_class, retention, timeout=540):
    pod_path = "/api/v1/namespaces/" + quote(namespace, safe="") + "/pods/" + quote(store + "-0", safe="")
    pause_until = 0
    identity = {}

    def check_pod():
        pod = api.call("GET", pod_path)
        volumes = {v["name"]: v.get("persistentVolumeClaim", {}).get("claimName")
                   for v in pod["spec"].get("volumes", [])}
        claims = {volumes.get(mount["name"]) for container in pod["spec"]["containers"]
                  for mount in container.get("volumeMounts", []) if mount["mountPath"] == "/data"}
        if (claims != {claim} or pod["metadata"].get("deletionTimestamp")
                or not any(c["type"] == "Ready" and c["status"] == "True"
                           for c in pod.get("status", {}).get("conditions", []))):
            raise RuntimeError("The Valkey Pod must be ready and use the selected data PVC.")
        return pod["metadata"]["uid"]

    def info(section):
        return dict(line.split(":", 1) for line in valkey.command("INFO", section).splitlines()
                    if ":" in line and not line.startswith("#"))

    def run_id():
        fields = info("server")
        if not fields.get("run_id"):
            raise RuntimeError("Valkey did not report its server identity.")
        return fields["run_id"]

    def prepare():
        nonlocal pause_until
        identity["pod"] = check_pod()
        identity["server"] = run_id()
        # Valkey also stops eviction and expiry during this pause. It expires after a killed Job.
        pause_until = time.monotonic() + 660
        if valkey.command("CLIENT", "PAUSE", 660000, "WRITE") != "OK":
            raise RuntimeError("Valkey did not pause writes.")
        if valkey.command("BGSAVE") != "Background saving started":
            raise RuntimeError("Valkey did not start its RDB save.")
        save_deadline = time.monotonic() + 90
        while True:
            persistence = info("persistence")
            if persistence.get("rdb_bgsave_in_progress") == "0":
                if persistence.get("rdb_last_bgsave_status") != "ok":
                    raise RuntimeError("Valkey failed to save its RDB file.")
                break
            if time.monotonic() >= save_deadline:
                raise RuntimeError("Valkey did not finish its RDB save before the deadline.")
            time.sleep(1)
        validate()

    def validate():
        if (check_pod() != identity["pod"] or run_id() != identity["server"]
                or time.monotonic() >= pause_until):
            raise RuntimeError("The Valkey server changed or its write pause expired during capture.")

    try:
        snapshots["backup"](api, namespace, store, claim, snapshot_class, retention,
                            timeout=timeout, label=LABEL, prepare=prepare, validate=validate,
                            verified_label=VERIFIED)
    finally:
        if pause_until:
            valkey.command("CLIENT", "UNPAUSE")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ("namespace", "store", "claim", "snapshot_class"):
        parser.add_argument(argument)
    parser.add_argument("retention", type=int)
    args = parser.parse_args()
    if not 1 <= args.retention <= 100:
        parser.error("retention must be from 1 to 100")
    password = Path("/var/run/valkey-backup/password").read_text()
    with closing(Valkey(args.store, password)) as valkey:
        capture(snapshots["API"](), valkey, args.namespace, args.store, args.claim,
                args.snapshot_class, args.retention)


if __name__ == "__main__":
    main()
