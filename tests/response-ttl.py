# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

import json
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
BUILDER = runpy.run_path(str(ROOT / "scripts/build-composition.py"))
RUNTIME_CHECK = """
import json
import sys

import grpc
from crossplane.function import response
from crossplane.function.proto.v1 import run_function_pb2 as fnv1
from crossplane.function.proto.v1 import run_function_pb2_grpc as fnv1_grpc

data = json.load(sys.stdin)
for case in data['cases']:
    for xr in data['xrs']:
        for step in case['pipeline']:
            req = fnv1.RunFunctionRequest()
            req.observed.composite.resource.update(xr)
            req.context.update({'apiextensions.crossplane.io/environment': data['environment']})
            req.input.update(step['input'])
            if step['input']['kind'] == 'Script':
                rsp = response.to(req)
                namespace = {}
                exec(compile(step['input']['script'], step['step'], 'exec'), namespace)
                namespace['compose'](req, rsp)
            else:
                with grpc.insecure_channel(data['auto_ready'] + ':9443') as channel:
                    stub = fnv1_grpc.FunctionRunnerServiceStub(channel)
                    rsp = stub.RunFunction(req, timeout=10)
            assert rsp.meta.ttl.seconds == case['seconds'], (step['step'], rsp.meta.ttl)
            assert rsp.meta.ttl.nanos == 0, (step['step'], rsp.meta.ttl)
"""


READINESS_CHECK = """
import json
import sys

from crossplane.function import response
from crossplane.function.proto.v1 import run_function_pb2 as fnv1

data = json.load(sys.stdin)
namespace = {}
exec(compile(data['check']['input']['script'], 'check-connection-readiness', 'exec'), namespace)
for resource_ready, connections, expected in (
    (fnv1.READY_TRUE, [{'ready': False}], fnv1.READY_FALSE),
    (fnv1.READY_TRUE, [{'ready': True}], fnv1.READY_TRUE),
    (fnv1.READY_FALSE, [{'ready': True}], fnv1.READY_FALSE),
    (fnv1.READY_TRUE, [], fnv1.READY_TRUE),
):
    req = fnv1.RunFunctionRequest()
    req.desired.composite.ready = resource_ready
    req.desired.composite.resource.update({'status': {'connections': connections}})
    rsp = response.to(req)
    namespace['compose'](req, rsp)
    assert rsp.desired.composite.ready == expected

req = fnv1.RunFunctionRequest()
req.observed.composite.resource.update({'metadata': {'name': 'readiness', 'namespace': 'workspace'}})
req.context.update({'apiextensions.crossplane.io/environment': {
    'customSecrets': [{'name': 'optional', 'namespace': 'shared-secrets'}],
}})
req.input.update(data['observe']['input'])
namespace = {}
exec(compile(data['observe']['input']['script'], 'observe-connection-secrets', 'exec'), namespace)
rsp = response.to(req)
namespace['compose'](req, rsp)
optional = [resource for resource in rsp.desired.resources.values()
            if resource.resource['spec']['forProvider']['manifest']['metadata']['name'] == 'optional']
assert len(optional) == 1 and optional[0].ready == fnv1.READY_TRUE
assert not any(item['type'] == 'custom'
               for item in rsp.desired.composite.resource['status']['connections'])
"""


class FunctionResponseTests(unittest.TestCase):
    def test_connection_readiness_preserves_optional_sources_and_resource_checks(self):
        pipeline = yaml.safe_load((ROOT / "composition.yaml").read_text())["spec"]["pipeline"]
        result = subprocess.run(
            ["docker", "exec", "-i", RUNTIME, "/venv/fn/bin/python", "-c", READINESS_CHECK],
            input=json.dumps({
                "check": next(step for step in pipeline if step["step"] == "check-connection-readiness"),
                "observe": next(step for step in pipeline if step["step"] == "observe-connection-secrets"),
            }),
            text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_all_generated_responses_use_setting(self):
        example = yaml.safe_load((ROOT / "examples/base/002-lab.yaml").read_text())
        empty = {
            "apiVersion": example["apiVersion"],
            "kind": example["kind"],
            "metadata": {"name": "ttl-check", "namespace": "workspace"},
            "spec": {"users": ["ttl-user"], "sessions": []},
        }
        environments = list(
            yaml.safe_load_all((ROOT / "tests/environmentconfig.yaml").read_text())
        )
        cases = []
        with tempfile.TemporaryDirectory(prefix="datalab-ttl-") as directory:
            root = Path(directory)
            shutil.copytree(ROOT / "composition", root / "composition")
            (root / "templates").symlink_to(
                ROOT / "templates", target_is_directory=True
            )
            for value in ("5m", "90s"):
                (root / "composition/settings.yaml").write_text(
                    yaml.safe_dump({"responseTTL": value})
                )

                composition = yaml.safe_load(BUILDER["build"](root))
                pipeline = composition["spec"]["pipeline"]
                cases.append(
                    {
                        "seconds": BUILDER["response_ttl_seconds"](value),
                        "pipeline": pipeline,
                    }
                )

            settings = (root / "composition/settings.yaml").read_text()
            composition = yaml.safe_load(BUILDER["build"](root, response_ttl="1m"))
            cases.append({"seconds": 60, "pipeline": composition["spec"]["pipeline"]})
            self.assertEqual((root / "composition/settings.yaml").read_text(), settings)

            pipeline = yaml.safe_load((root / "composition/pipeline.yaml").read_text())
            pipeline["spec"]["pipeline"].append(
                {"step": "unsupported", "functionRef": {"name": "unsupported-function"}}
            )
            (root / "composition/pipeline.yaml").write_text(yaml.safe_dump(pipeline))
            with self.assertRaisesRegex(ValueError, "No response TTL configuration"):
                BUILDER["build"](root)

        result = subprocess.run(
            [
                "docker",
                "exec",
                "-i",
                RUNTIME,
                "/venv/fn/bin/python",
                "-c",
                RUNTIME_CHECK,
            ],
            input=json.dumps(
                {
                    "cases": cases,
                    "xrs": [empty, example],
                    "environment": environments[0]["data"],
                    "auto_ready": RUNTIME.removesuffix("-python") + "-auto-ready",
                }
            ),
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(
            "Usage: python3 tests/response-ttl.py <Python function container>"
        )
    RUNTIME = sys.argv.pop()
    unittest.main()
