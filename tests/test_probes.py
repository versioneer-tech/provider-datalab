# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Require usable probes on managed workloads and package runtimes."""

from pathlib import Path
from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
import json
import runpy
import subprocess
import sys
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


class ProbeTests(unittest.TestCase):
    def test_crossplane_chart_output_has_probes_and_rejects_missing_components(self):
        deployments = [
            {"apiVersion": "apps/v1", "kind": "Deployment", "metadata": {"name": component},
             "spec": {"template": {"spec": {
                 "initContainers": [{"name": "init", "args": [component, "init"]}],
                 "containers": [{"name": "crossplane", "args": [component, "start"]}]}}}}
            for component in ("core", "rbac")
        ]
        command = [sys.executable, str(ROOT / "scripts/crossplane-probes.py")]
        result = subprocess.run(command, input=yaml.safe_dump_all(deployments), text=True,
                                capture_output=True, check=True)
        for deployment in yaml.safe_load_all(result.stdout):
            pod = deployment["spec"]["template"]["spec"]
            self.assertNotIn("livenessProbe", pod["initContainers"][0])
            for name in ("startupProbe", "readinessProbe", "livenessProbe"):
                self.assertIn("httpGet", pod["containers"][0][name])
        missing = subprocess.run(command, input=yaml.safe_dump(deployments[0]), text=True, capture_output=True)
        self.assertNotEqual(missing.returncode, 0)
        self.assertEqual(missing.stdout, "")

    def test_live_gate_requires_ready_probed_containers_and_ignores_finite_jobs(self):
        healthy = {"metadata": {"name": "test-service"},
                   "spec": {"containers": [{"name": "server", "readinessProbe": {}, "livenessProbe": {}}]},
                   "status": {"containerStatuses": [{"name": "server", "ready": True, "state": {"running": {}}}]}}
        missing = deepcopy(healthy)
        del missing["spec"]["containers"][0]["livenessProbe"]
        unready = deepcopy(healthy)
        unready["status"]["containerStatuses"][0]["ready"] = False
        job = {"metadata": {"name": "test-job"},
               "spec": {"restartPolicy": "Never", "containers": [{"name": "task"}]}}
        script = ROOT / "tests/integration/verify-probes.py"
        arguments = [str(script), "--kubeconfig", "/test/cluster", "--context", "test-cluster", "--namespace", "test"]
        for pods, accepted in (([healthy], True), ([healthy, job], True), ([missing], False),
                               ([unready], False), ([job], False), ([], False)):
            with self.subTest(pods=pods), patch("sys.argv", arguments), \
                    patch("subprocess.check_output", return_value=json.dumps({"items": pods})), \
                    patch("time.monotonic", side_effect=[0, 601]), redirect_stdout(StringIO()) as output:
                if accepted:
                    runpy.run_path(str(script))
                    self.assertIn("PASS", output.getvalue())
                else:
                    with self.assertRaises(AssertionError):
                        runpy.run_path(str(script))
                    self.assertNotIn("PASS", output.getvalue())

    def test_long_running_containers_have_probes_with_resolvable_ports(self):
        paths = [ROOT / "dependencies/01-deploymentRuntimeConfigs.yaml",
                 ROOT / "examples/vcluster/stac-fastapi.yaml"]
        paths.extend(sorted((ROOT / "tests/expected").glob("*.yaml")))
        checked = set()
        for path in paths:
            for body in yaml.load_all(path.read_text(), Loader=LOADER):
                if body.get("kind") == "Object":
                    body = body["spec"]["forProvider"]["manifest"]
                if body.get("kind") == "DeploymentRuntimeConfig":
                    pod = body["spec"]["deploymentTemplate"]["spec"]["template"]["spec"]
                elif body.get("kind") in ("Deployment", "StatefulSet", "DaemonSet"):
                    pod = body["spec"]["template"]["spec"]
                else:
                    continue
                for container in pod["containers"]:
                    identity = (body["kind"], body["metadata"]["name"], container["name"])
                    checked.add(identity)
                    for kind in ("startupProbe", "readinessProbe", "livenessProbe"):
                        with self.subTest(path=path.name, container=identity, probe=kind):
                            probe = container[kind]
                            handlers = set(probe) & {"httpGet", "tcpSocket", "exec", "grpc"}
                            self.assertEqual(len(handlers), 1)
                            handler = probe[next(iter(handlers))]
                            port = handler.get("port")
                            if isinstance(port, str):
                                self.assertIn(port, {p["name"] for p in container.get("ports", [])})
                            elif port is not None:
                                self.assertTrue(1 <= port <= 65535)
                            else:
                                self.assertTrue(handler.get("command"))
        self.assertTrue(checked)


if __name__ == "__main__":
    unittest.main()
