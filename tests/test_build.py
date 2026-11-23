# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Check composition builds and response TTL input."""

import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from helpers import BUILDER, ROOT


class BuildTests(unittest.TestCase):
    def test_build_rejects_duplicate_pipeline_steps(self):
        with TemporaryDirectory(prefix="test-pipeline-") as directory:
            root = Path(directory)
            (root / "composition").mkdir()
            (root / "composition/settings.yaml").write_text("responseTTL: 5m\n")
            (root / "composition/pipeline.yaml").write_text(
                "spec:\n  pipeline:\n  - step: registry\n  - step: registry\n"
            )
            with self.assertRaisesRegex(ValueError, "step names must be unique"):
                BUILDER["build"](root)

    def test_ttl_override_cannot_replace_deployment_artifact(self):
        artifact = ROOT / "composition.yaml"
        original = artifact.read_bytes()
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts/build-composition.py"), "--response-ttl", "1m"],
            capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires a separate --output", result.stderr)
        self.assertEqual(artifact.read_bytes(), original)

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


if __name__ == "__main__":
    unittest.main()
