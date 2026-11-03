# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Report CPU requests from active Pods and the node allocation."""

from collections import defaultdict
from decimal import Decimal
import json
import sys


def millicpu(value):
    text = str(value or "0")
    for suffix, factor in (
        ("n", Decimal("0.000001")),
        ("u", Decimal("0.001")),
        ("m", 1),
    ):
        if text.endswith(suffix):
            return Decimal(text[:-1]) * factor
    return Decimal(text) * 1000


def pod_request(spec):
    regular = sum(
        millicpu((c.get("resources") or {}).get("requests", {}).get("cpu"))
        for c in spec.get("containers", [])
    )
    sidecars = Decimal(0)
    peak = Decimal(0)
    for container in spec.get("initContainers", []):
        request = millicpu(
            (container.get("resources") or {}).get("requests", {}).get("cpu")
        )
        if container.get("restartPolicy") == "Always":
            sidecars += request
            peak = max(peak, sidecars)
        else:
            peak = max(peak, sidecars + request)
    return max(regular + sidecars, peak) + millicpu(spec.get("overhead", {}).get("cpu"))


def main():
    data = json.load(sys.stdin)
    requests = defaultdict(Decimal)
    assigned = defaultdict(Decimal)
    unscheduled = Decimal(0)
    for pod in data["pods"]:
        if pod.get("status", {}).get("phase") in ("Succeeded", "Failed"):
            continue
        request = pod_request(pod["spec"])
        requests[pod["metadata"]["namespace"]] += request
        node = pod["spec"].get("nodeName")
        if node:
            assigned[node] += request
        else:
            unscheduled += request
    print("CPU request budget (millicores):")
    for namespace, request in sorted(requests.items()):
        print(f"  {namespace}: {request:g}m")
    for node in data["nodes"]:
        capacity = millicpu(node["status"]["allocatable"]["cpu"])
        request = assigned[node["metadata"]["name"]]
        print(
            f"  node {node['metadata']['name']}: {request:g}m requested, {capacity:g}m allocatable, {capacity - request:g}m free"
        )
    print(f"  unscheduled Pods: {unscheduled:g}m requested")


if __name__ == "__main__":
    main()
