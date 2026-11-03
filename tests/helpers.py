# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

import runpy
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
inline_helpers = runpy.run_path(str(ROOT / "scripts/build-composition.py"))[
    "inline_helpers"
]
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
        for size in (None, "", "0", "0Gi", "0.0G", "0e3"):
            with self.subTest(size=size):
                self.assertFalse(enabled(size))
        for size in ("1Gi", "0.5Gi", ".5G", "1e-3", "+1Mi", "1m"):
            with self.subTest(size=size):
                self.assertTrue(enabled(size))
        for size in ("-1Gi", "invalid", "1GB"):
            with self.subTest(size=size):
                with self.assertRaisesRegex(ValueError, "backupStorage"):
                    enabled(size)

    def test_service_tokens_do_not_change(self):
        token = load_helpers("_strong_token")["_strong_token"]
        self.assertEqual(token("sample:mongo"), "4YlC2SJsBu45oGi9FbJZFBypWCpXR-vU")
        self.assertEqual(
            token("sample:redis", suffix="", length=28), "E6xDTnRLBJ1XV75rV3xJDiEsGpHp"
        )


class IntegrationHarnessTests(unittest.TestCase):
    def test_http_and_command_errors_do_not_prove_network_isolation(self):
        script = '''
source "$1"
xyz_exit="$2"
kube() { return "$xyz_exit"; }
verify_connection probe workspace block unused
'''
        for code in (0, 1, 6, 7, 22, 28):
            with self.subTest(exit_code=code):
                result = subprocess.run(
                    ["bash", "-c", script, "xyz",
                     str(ROOT / "tests/integration/verify-network.bash"), str(code)],
                    capture_output=True, text=True, check=True,
                )
                expected = "PASS" if code in (7, 28) else "FAIL"
                self.assertTrue(result.stdout.startswith(f"{expected} probe"), result.stdout)

    def test_ingress_certificate_reuse_requires_the_correct_hostname(self):
        script = '''
set -euo pipefail
source "$1"
xyz_source="$2"
xyz_applied="$3"
WORKSPACE_NAMESPACE=workspace
require_command() { command -v "$1" >/dev/null; }
kube() {
  case "$1" in
    get) base64 <"$xyz_source" ;;
    create)
      while (($#)); do
        if [[ "$1" == --cert ]]; then
          cat "$2"
          return
        fi
        shift
      done
      return 1
      ;;
    apply) cat >"$xyz_applied" ;;
    *) return 1 ;;
  esac
}
create_ingress_certificate
'''
        with tempfile.TemporaryDirectory(prefix="xyz-cert-") as directory:
            work = Path(directory)
            for hostname, renewed in (("*.lab.acme.com", False), ("*.old.acme.com", True)):
                with self.subTest(hostname=hostname):
                    certificate = work / "source.crt"
                    applied = work / "applied.crt"
                    subprocess.run(
                        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                         "-subj", f"/CN={hostname}", "-addext", f"subjectAltName=DNS:{hostname}",
                         "-keyout", str(work / "key"), "-out", str(certificate)],
                        capture_output=True, check=True,
                    )
                    subprocess.run(
                        ["bash", "-c", script, "xyz", str(ROOT / "tests/integration/educates.bash"),
                         str(certificate), str(applied)],
                        capture_output=True, text=True, check=True,
                    )
                    self.assertEqual(applied.exists(), renewed)
                    if renewed:
                        subprocess.run(
                            ["openssl", "x509", "-in", str(applied), "-noout",
                             "-checkhost", "verify-data.lab.acme.com"],
                            capture_output=True, check=True,
                        )


if __name__ == "__main__":
    unittest.main()
