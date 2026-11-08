# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Check that documentation selection cannot skip runtime changes."""

from pathlib import Path
import runpy
import subprocess
import sys
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ci-checks.py"
CHECKS = runpy.run_path(str(SCRIPT))


class CheckSelectionTests(unittest.TestCase):
    def test_documentation_changes(self):
        self.assertTrue(CHECKS["documentation_only"]([
            "README.md", "docs/requirements.txt", "mkdocs.yml",
        ]))

    def test_runtime_and_unknown_paths_require_full_checks(self):
        for path in ["composition.yaml", "xrd.yaml", "templates/keycloak/client.yaml",
                     "scripts/ci-checks.py", "tests/ci-checks.py", ".github/workflows/pr.yaml", "unknown.txt"]:
            with self.subTest(path=path):
                self.assertFalse(CHECKS["documentation_only"](["README.md", path]))

    def test_untracked_code_requires_full_checks(self):
        def git(*arguments):
            if arguments[0] == "rev-parse":
                return b"1234\n"
            return b"README.md\0" if arguments[0] == "diff" else b"scripts/new.py\0"

        with patch.dict(CHECKS["select_checks"].__globals__, {"git": git}):
            self.assertFalse(CHECKS["select_checks"]("HEAD"))

    def test_empty_or_unavailable_comparison_requires_full_checks(self):
        for arguments in [[], ["--base", "0" * 40, "--head", "HEAD"],
                          ["--base", "HEAD", "--head", "HEAD"]]:
            with self.subTest(arguments=arguments):
                result = subprocess.run([sys.executable, str(SCRIPT), *arguments],
                                        capture_output=True, text=True, check=True)
                self.assertEqual(result.stdout, "docs_only=false\n")


if __name__ == "__main__":
    unittest.main()
