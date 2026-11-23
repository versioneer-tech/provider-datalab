#!/usr/bin/env python3
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Check OAuth credential rotation, workload restart, and recovery."""

import argparse
import base64
import json
import subprocess
import time
import uuid

DATALAB = "verify-s3"
WORKSPACE = "workspace"
CLIENT = f"client.openidclient.keycloak.m.crossplane.io/{DATALAB}"
SOURCE = f"secret/{DATALAB}-oauth-client"
OBSERVER = f"object.kubernetes.m.crossplane.io/observe-oauth-client-secret-{DATALAB}"
PAUSED = "crossplane.io/paused"
CHECKSUM = "datalabs.versioneer.at/oauth2-cookie-checksum"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kubeconfig", required=True)
    parser.add_argument("--context", default="kind-provider-datalab-it")
    parser.add_argument("--namespace", required=True)
    args = parser.parse_args()

    def kube(*arguments, data=None):
        result = subprocess.run(
            [
                "kubectl",
                "--kubeconfig",
                args.kubeconfig,
                "--context",
                args.context,
                *arguments,
            ],
            input=json.dumps(data) if data is not None else None,
            text=True,
            capture_output=True,
            timeout=180,
        )
        if result.returncode:
            # Secret command output can contain credentials on failure.
            raise RuntimeError(f"Kubernetes command failed: {' '.join(arguments[:2])}")
        return result.stdout

    def get(resource, namespace=WORKSPACE):
        return json.loads(kube("get", resource, "--namespace", namespace, "-o", "json"))

    def patch(resource, body):
        kube(
            "patch",
            resource,
            "--namespace",
            WORKSPACE,
            "--type=merge",
            "--patch-file=/dev/stdin",
            data=body,
        )

    def wait_for(check, message, timeout=120):
        deadline = time.monotonic() + timeout
        while not check():
            if time.monotonic() >= deadline:
                raise RuntimeError(message)
            time.sleep(2)

    observer = get(OBSERVER)
    assert observer["status"]["atProvider"]["manifest"].get("data") == {"redacted": None}, (
        "The OAuth observer exposes Secret data."
    )
    original = get(SOURCE)["data"]
    secret_key = next(
        key
        for key in ("clientSecret", "client_secret")
        if original.get(key)
    )
    previous_pause = get(CLIENT)["metadata"].get("annotations", {}).get(PAUSED)
    assert previous_pause != "true", "The test client is already paused."

    def checksums():
        return tuple(
            get(f"deployment/{name}", args.namespace)["spec"]["template"]["metadata"][
                "annotations"
            ].get(CHECKSUM)
            for name in ("package-r", "data-s3")
        )

    def propagated(encoded, previous):
        observed = get(OBSERVER)["status"]["atProvider"]["manifest"]
        source_version = get(SOURCE)["metadata"]["resourceVersion"]
        runtime = get(f"secret/{DATALAB}-oauth2-client", args.namespace)["data"]
        if (
            observed.get("data") != {"redacted": None}
            or observed.get("metadata", {}).get("resourceVersion") != source_version
            or runtime.get("client_secret") != encoded
        ):
            return False
        return all(current and current != old for current, old in zip(checksums(), previous))

    def rollouts():
        for name in ("package-r", "data-s3"):
            kube(
                "rollout",
                "status",
                f"deployment/{name}",
                "--namespace",
                args.namespace,
                "--timeout=120s",
            )

    try:
        # Pause the producer so its next poll cannot overwrite the test value.
        patch(CLIENT, {"metadata": {"annotations": {PAUSED: "true"}}})
        wait_for(
            lambda: any(
                condition.get("reason") == "ReconcilePaused"
                for condition in get(CLIENT)["status"]["conditions"]
            ),
            "The test client did not pause.",
        )
        rotated = base64.b64encode(f"oauth-watch-{uuid.uuid4().hex}".encode()).decode()
        previous = checksums()
        patch(SOURCE, {"data": {secret_key: rotated}})
        wait_for(
            lambda: propagated(rotated, previous), "The OAuth Secret update did not propagate."
        )
        print(
            "PASS OAuth credentials propagate to both workloads",
            flush=True,
        )
        rollouts()
        previous = checksums()
    finally:
        try:
            patch(SOURCE, {"data": {secret_key: original[secret_key]}})
        finally:
            patch(CLIENT, {"metadata": {"annotations": {PAUSED: previous_pause}}})

    wait_for(
        lambda: propagated(original[secret_key], previous),
        "The OAuth credentials were not restored.",
        timeout=300,
    )
    rollouts()
    wait_for(
        lambda: any(
            condition.get("type") == "Synced" and condition.get("status") == "True"
            for condition in get(CLIENT)["status"]["conditions"]
        ),
        "The test client did not resume.",
    )

    print("PASS restored credentials and workload readiness", flush=True)


if __name__ == "__main__":
    main()
