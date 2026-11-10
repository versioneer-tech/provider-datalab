#!/usr/bin/env python3
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Check host namespace resource defaults and quota admission."""

import argparse
import json
import subprocess
import time


def verify(kubeconfig, namespace):
    command = [
        "kubectl", "--kubeconfig", kubeconfig, "--context", "kind-provider-datalab-it",
        "--namespace", namespace,
    ]

    def get(resource):
        result = subprocess.run([*command, "get", resource, "-o", "json"],
                                capture_output=True, text=True, check=True)
        return json.loads(result.stdout)

    deadline = time.monotonic() + 120
    while True:
        quota = get("resourcequota/overall-storage")
        hard = quota["spec"]["hard"]
        if quota.get("status", {}).get("hard") == hard:
            break
        assert time.monotonic() < deadline, "Host quota status did not become current"
        time.sleep(2)
    assert {key: hard[key] for key in (
        "requests.cpu", "requests.memory", "limits.cpu", "limits.memory",
    )} == {
        "requests.cpu": "4", "requests.memory": "8Gi",
        "limits.cpu": "16", "limits.memory": "32Gi",
    }
    limits = get("limitrange/datalab-limits")["spec"]["limits"][0]

    def admit(resources):
        pod = {
            "apiVersion": "v1", "kind": "Pod",
            "metadata": {"name": "test-resource-limits"},
            "spec": {"containers": [{"name": "probe", "image": "nginx:1.27-alpine",
                                      "resources": resources}]},
        }
        return subprocess.run(
            [*command, "create", "--dry-run=server", "-f", "-", "-o", "json"],
            input=json.dumps(pod), capture_output=True, text=True,
        )

    result = admit({})
    assert result.returncode == 0, result.stderr
    resources = json.loads(result.stdout)["spec"]["containers"][0]["resources"]
    assert resources == {"limits": limits["default"], "requests": limits["defaultRequest"]}
    for field, value in (
        ("requests.cpu", "5"), ("requests.memory", "9Gi"),
        ("limits.cpu", "17"), ("limits.memory", "33Gi"),
    ):
        kind, resource = field.split(".")
        resources = {"requests": {"cpu": "100m", "memory": "128Mi"},
                     "limits": {"cpu": "1", "memory": "512Mi"}}
        resources[kind][resource] = value
        if kind == "requests":
            resources["limits"][resource] = value
        result = admit(resources)
        assert result.returncode != 0 and "exceeded quota" in result.stderr and field in result.stderr, result.stderr
    print(f"PASS {namespace}: host LimitRange defaults and CPU/memory quota rejection", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kubeconfig", required=True)
    parser.add_argument("namespaces", nargs="+")
    args = parser.parse_args()
    for namespace in args.namespaces:
        verify(args.kubeconfig, namespace)
