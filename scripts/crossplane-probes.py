#!/usr/bin/env python3
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Add health probes to the Crossplane Helm output."""

from copy import deepcopy
import sys

import yaml

from components import pin_images


documents = [item for item in yaml.safe_load_all(sys.stdin) if item is not None]
found = set()
for document in documents:
    if not document or document.get("kind") != "Deployment":
        continue
    for container in document["spec"]["template"]["spec"]["containers"]:
        command = tuple(container.get("args", [])[:2])
        if command not in (("core", "start"), ("rbac", "start")):
            continue
        found.add(command[0])
        # The RBAC manager has no health endpoint in the pinned release.
        port = 8081 if command[0] == "core" else 8080
        live = "/healthz" if command[0] == "core" else "/metrics"
        ready = "/readyz" if command[0] == "core" else "/metrics"
        for name, path, period, failures in (
            ("startupProbe", live, 5, 60),
            ("readinessProbe", ready, 10, 3),
            ("livenessProbe", live, 10, 6),
        ):
            container.setdefault(name, deepcopy({
                "httpGet": {"path": path, "port": port},
                "periodSeconds": period,
                "timeoutSeconds": 3,
                "failureThreshold": failures,
            }))
if found != {"core", "rbac"}:
    raise SystemExit("Expected the Crossplane core and RBAC manager Deployments in Helm output.")
yaml.safe_dump_all(pin_images(documents), sys.stdout, sort_keys=False)
