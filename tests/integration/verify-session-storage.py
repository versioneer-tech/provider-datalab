#!/usr/bin/env python3
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Check published session requests and retained storage through stop/start."""

import argparse
import json
import subprocess
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kubeconfig", required=True)
    args = parser.parse_args()
    command = ["kubectl", "--kubeconfig", args.kubeconfig, "--context", "kind-provider-datalab-it"]

    def kube(*arguments):
        result = subprocess.run(command + list(arguments), capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, "Session storage check failed: " + " ".join(arguments[:3])
        return json.loads(result.stdout) if arguments[0] == "get" and result.stdout.strip() else None

    def get(kind, name, namespace="workspace"):
        return kube("get", kind, name, "--namespace", namespace, "--ignore-not-found", "-o", "json")

    def wait_for(check):
        deadline = time.monotonic() + 900
        while True:
            try:
                return check()
            except (AssertionError, KeyError, TypeError):
                if time.monotonic() >= deadline:
                    raise
                time.sleep(3)

    def current(state):
        status = get("datalab", "verify-registry")["status"]
        sessions = {entry["name"]: entry for entry in status["sessions"]}
        assert set(sessions) == {"default", "saved"}
        assert "resourceUsage" not in status
        volumes = {}
        for name, entry in sessions.items():
            assert entry["pvcSize"] == "2Gi"
            ref = entry["pvcRef"]
            pvc = get("persistentvolumeclaim", ref["name"], ref["namespace"])
            assert pvc["spec"]["resources"]["requests"]["storage"] == entry["pvcSize"]
            volumes[name] = pvc["metadata"]["uid"]
        assert len(set(volumes.values())) == 2
        assert sessions["saved"]["state"] == "stopped" and "url" not in sessions["saved"]
        active = sessions["default"]
        assert active["state"] == state
        if state == "started":
            assert active.get("phase") == "Running" and active.get("url")
        else:
            assert not any(field in active for field in ("phase", "message", "url"))
            assert get("objects.kubernetes.m.crossplane.io", "workshopsession-verify-registry-default") is None
        return volumes

    original = wait_for(lambda: current("started"))
    for state in ("stopped", "started"):
        patch = {"spec": {"sessions": [{"name": "default", "state": state}, {"name": "saved", "state": "stopped"}]}}
        kube("patch", "datalab", "verify-registry", "--namespace", "workspace", "--type=merge", "--patch", json.dumps(patch))

        def unchanged():
            assert current(state) == original, "Stopping or restarting replaced a persistent session PVC"
        wait_for(unchanged)
    print("PASS session sizes match effective requests, exclude registry storage, and survive stop/start with the same PVCs", flush=True)


if __name__ == "__main__":
    main()
