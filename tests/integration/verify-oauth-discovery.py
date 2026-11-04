#!/usr/bin/env python3
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Check OAuth2 discovery after source Secret deletion and recovery in Kind."""

import argparse
import json
import subprocess
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kubeconfig", required=True)
    parser.add_argument("--datalab", required=True)
    args = parser.parse_args()

    def kube(*arguments, body=None, json_output=True):
        result = subprocess.run(
            ["kubectl", "--kubeconfig", args.kubeconfig, "--context", "kind-provider-datalab-it",
             "--namespace", "workspace", *arguments],
            input=json.dumps(body) if body is not None else None,
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode:
            raise RuntimeError("OAuth2 discovery test Kubernetes call failed: " + " ".join(arguments[:2]))
        return json.loads(result.stdout) if json_output and result.stdout.strip() else None

    def get(resource):
        return kube("get", resource, "-o", "json")

    def patch(resource, body):
        return kube("patch", resource, "--type=merge", "--patch-file=/dev/stdin", "-o", "json", body=body)

    def wait_for(check, message):
        deadline = time.monotonic() + 180
        while not check():
            if time.monotonic() >= deadline:
                raise RuntimeError(message)
            time.sleep(2)

    source = f"secret/{args.datalab}-oauth-client"
    client = f"client.openidclient.keycloak.m.crossplane.io/{args.datalab}"
    datalab = f"datalab/{args.datalab}"
    paused = "crossplane.io/paused"
    client_state = get(client)
    previous_pause = client_state["metadata"].get("annotations", {}).get(paused)
    assert previous_pause != "true", "The test client is already paused."
    original = get(source)
    restored = {
        "apiVersion": "v1", "kind": "Secret", "type": original["type"],
        "metadata": {key: value for key, value in original["metadata"].items()
                     if key in ("name", "namespace", "ownerReferences", "labels")},
        "data": original["data"],
    }
    deleted = False
    try:
        patch(client, {"metadata": {"annotations": {paused: "true"}}})
        wait_for(lambda: any(c.get("reason") == "ReconcilePaused" for c in get(client)["status"]["conditions"]),
                 "The OAuth2 test client did not pause.")
        kube("delete", source, json_output=False)
        deleted = True
        wait_for(lambda: get(datalab)["status"].get("oauth2") == [],
                 "OAuth2 discovery retained a removed credential Secret.")
        print("PASS removed credential Secret clears OAuth2 discovery despite cached observer data", flush=True)
    finally:
        try:
            if deleted:
                kube("create", "-f", "-", "-o", "json", body=restored)
        finally:
            patch(client, {"metadata": {"annotations": {paused: previous_pause}}})
    client_id = client_state["spec"]["forProvider"]["clientId"]
    wait_for(lambda: get(datalab)["status"].get("oauth2") == [{
        "name": client_id,
        "type": "client",
        "issuerUrl": "https://keycloak.keycloak:8443/realms/integration",
        "secretRef": {"name": args.datalab + "-oauth-client", "namespace": "workspace"},
        "ready": True,
    }], "OAuth2 discovery did not recover after restoring its source.")
    print("PASS OAuth2 discovery recovers with the original workspace credential", flush=True)


if __name__ == "__main__":
    main()
