#!/usr/bin/env python3
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Check OAuth Secret updates, workload restart, and idle state in Kind."""

import argparse
import base64
import hashlib
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
    parser.add_argument("--namespace", required=True)
    args = parser.parse_args()

    def kube(*arguments, data=None):
        result = subprocess.run(
            [
                "kubectl",
                "--kubeconfig",
                args.kubeconfig,
                "--context",
                "kind-provider-datalab-it",
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

    # The startup circuit condition can stay stale until the next watch event.
    observer = get(OBSERVER)
    assert observer["spec"]["watch"] is True, "The OAuth observer is not watched."
    original = get(SOURCE)["data"]
    secret_key = next(
        key
        for key in ("clientSecret", "client_secret")
        if original.get(key)
    )
    previous_pause = get(CLIENT)["metadata"].get("annotations", {}).get(PAUSED)
    assert previous_pause != "true", "The test client is already paused."

    def propagated(encoded):
        raw = base64.b64decode(encoded)
        cookie_secret = hashlib.sha256(raw).hexdigest()[:32]
        checksum = hashlib.sha256(cookie_secret.encode()).hexdigest()
        observed_data = get(OBSERVER)["status"]["atProvider"]["manifest"].get(
            "data", {}
        )
        runtime = get(f"secret/{DATALAB}-oauth2-client", args.namespace)["data"]
        if (
            observed_data.get(secret_key) != encoded
            or runtime.get("client_secret") != encoded
        ):
            return False
        return all(
            get(f"deployment/{name}", args.namespace)["spec"]["template"]["metadata"][
                "annotations"
            ].get(CHECKSUM)
            == checksum
            for name in ("package-r", "data-s3")
        )

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
        started = time.monotonic()
        patch(SOURCE, {"data": {secret_key: rotated}})
        wait_for(
            lambda: propagated(rotated), "The OAuth Secret update did not propagate."
        )
        print(
            f"PASS watched OAuth Secret propagation in {time.monotonic() - started:.1f} seconds",
            flush=True,
        )
        rollouts()
    finally:
        try:
            patch(SOURCE, {"data": {secret_key: original[secret_key]}})
        finally:
            patch(CLIENT, {"metadata": {"annotations": {PAUSED: previous_pause}}})

    # Recovery can cross the watch circuit's backoff window.
    wait_for(
        lambda: propagated(original[secret_key]),
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

    def versions():
        return tuple(
            get(resource, namespace)["metadata"]["resourceVersion"]
            for resource, namespace in (
                (SOURCE, WORKSPACE),
                (OBSERVER, WORKSPACE),
                (f"secret/{DATALAB}-oauth2-client", args.namespace),
            )
        )

    previous = versions()
    unchanged_since = time.monotonic()
    deadline = unchanged_since + 180
    while time.monotonic() - unchanged_since < 30:
        if time.monotonic() >= deadline:
            raise RuntimeError("The OAuth Secret chain did not settle.")
        time.sleep(2)
        current = versions()
        if current != previous:
            previous = current
            unchanged_since = time.monotonic()
    print(
        "PASS restored OAuth credentials, workload restarts, and 30 seconds without Secret-chain updates",
        flush=True,
    )


if __name__ == "__main__":
    main()
