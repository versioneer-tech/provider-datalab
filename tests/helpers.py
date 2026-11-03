# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

import runpy
import re
import subprocess
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
BUILDER = runpy.run_path(str(ROOT / "scripts/build-composition.py"))
inline_helpers = BUILDER["inline_helpers"]
HELPER_SOURCE = (ROOT / "composition/helpers.py").read_text()


def load_helpers(*names):
    script = f"from composition.helpers import {', '.join(names)}\n"
    namespace = {}
    # Run the embedded code without a repository module in the function runtime.
    exec(inline_helpers(script, HELPER_SOURCE), namespace)
    return namespace


class HelperTests(unittest.TestCase):
    def test_backup_size_controls_enablement(self):
        enabled = load_helpers("_backup_enabled")["_backup_enabled"]
        for size in (None, "", "0", "0Gi", "0.0Gi", "0.0G", "0e3"):
            with self.subTest(size=size):
                self.assertFalse(enabled(size))
        for size in ("1Gi", "0.5Gi", ".5G", "1e3", "1e-3", "+1Mi", "1m"):
            with self.subTest(size=size):
                self.assertTrue(enabled(size))
        for size in ("-1Gi", "invalid", "1GB"):
            with self.subTest(size=size):
                with self.assertRaisesRegex(ValueError, "backupStorage"):
                    enabled(size)

    def test_backup_schema_accepts_only_non_negative_quantities(self):
        xrd = yaml.safe_load((ROOT / "xrd.yaml").read_text())
        version = next(item for item in xrd["spec"]["versions"] if item["referenceable"])
        schema = version["schema"]["openAPIV3Schema"]["properties"]["spec"]["properties"]
        for field in ("databases", "documentStores", "cacheStores"):
            quantity = schema[field]["additionalProperties"]["properties"]["backupStorage"]
            with self.subTest(field=field):
                self.assertEqual(quantity["default"], "0")
                self.assertEqual(quantity["type"], "string")
                for value in ("0", "0Gi", "0.0Gi", "1Gi", ".5G", "1e3"):
                    self.assertIsNotNone(re.fullmatch(quantity["pattern"], value), value)
                for value in ("", "-1Gi", "invalid", "1GB"):
                    self.assertIsNone(re.fullmatch(quantity["pattern"], value), value)

    def test_service_tokens_do_not_change(self):
        token = load_helpers("_strong_token")["_strong_token"]
        self.assertEqual(token("sample:mongo"), "4YlC2SJsBu45oGi9FbJZFBypWCpXR-vU")
        self.assertEqual(
            token("sample:redis", suffix="", length=28), "E6xDTnRLBJ1XV75rV3xJDiEsGpHp"
        )


class BuildAndHarnessTests(unittest.TestCase):
    def test_duration_units(self):
        for value, seconds in (("30s", 30), ("5m", 300), ("1h", 3600)):
            with self.subTest(value=value):
                self.assertEqual(BUILDER["response_ttl_seconds"](value), seconds)

    def test_invalid_durations_fail(self):
        for value in (
            None,
            True,
            300,
            "",
            "0s",
            "-1m",
            "1.5s",
            "1m30s",
            "5",
            "5d",
            "9223372037s",
        ):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    BUILDER["response_ttl_seconds"](value)


    def test_http_and_command_errors_do_not_prove_network_isolation(self):
        script = '''
source "$1"
test_exit="$2"
kube() { return "$test_exit"; }
verify_connection probe workspace block unused
'''
        for code in (0, 1, 6, 7, 22, 28):
            with self.subTest(exit_code=code):
                result = subprocess.run(
                    ["bash", "-c", script, "test",
                     str(ROOT / "tests/integration/verify-network.bash"), str(code)],
                    capture_output=True, text=True, check=True,
                )
                expected = "PASS" if code in (7, 28) else "FAIL"
                self.assertTrue(result.stdout.startswith(f"{expected} probe"), result.stdout)


if __name__ == "__main__":
    unittest.main()
