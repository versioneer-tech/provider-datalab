# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Check that Valkey waits for the current projected ACL before startup."""

import base64
import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml


class ValkeyACLTests(unittest.TestCase):
    def test_stale_projection_blocks_startup_until_current_acl_arrives(self):
        root = Path(__file__).resolve().parents[1]
        template = yaml.safe_load((root / "templates/valkey/store.yaml").read_text())
        command = template["spec"]["template"]["spec"]["initContainers"][0]["command"]
        current = b"user default on nopass ~* +@all\nuser backup on nopass +ping\n"
        expected = hashlib.sha256(base64.b64encode(current)).hexdigest()
        with tempfile.TemporaryDirectory() as temporary:
            acl = Path(temporary) / "user.acl"
            acl.write_text("user default on nopass ~* +@all\n")
            process = subprocess.Popen([*command[:4], expected, str(acl)],
                                       env={"PATH": "/usr/bin:/bin"}, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                with self.assertRaises(subprocess.TimeoutExpired):
                    process.communicate(timeout=0.2)
                acl.write_bytes(current)
                _, errors = process.communicate(timeout=5)
                self.assertEqual(process.returncode, 0, errors.decode())
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.communicate(timeout=5)


if __name__ == "__main__":
    unittest.main()
