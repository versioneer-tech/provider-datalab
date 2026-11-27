# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Check installed platform content and scan inventory boundaries."""

import hashlib
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = runpy.run_path(str(ROOT / "scripts/components.py"))
SECURITY = runpy.run_path(str(ROOT / "scripts/security.py"))


class ComponentTests(unittest.TestCase):
    def test_production_scope_keeps_platform_and_shared_images(self):
        production = set(SECURITY["external_images"](ROOT, "production"))
        tests = set(SECURITY["external_images"](ROOT, "test"))
        self.assertFalse(production & tests)
        self.assertEqual(production | tests, set(SECURITY["external_images"](ROOT)))
        for name in ("cloudnative-pg/cloudnative-pg:", "crossplane/crossplane:",
                     "cloudnative-pg/postgis:", "nginx-unprivileged:"):
            with self.subTest(name=name):
                self.assertTrue(any(name in ref for ref in production))
                self.assertFalse(any(name in ref for ref in tests))
        self.assertTrue(any(ref.startswith("python:") and "alpine" in ref for ref in production))
        for name in ("alpine/minio:", "kindest/node:", "keycloak/keycloak:"):
            self.assertTrue(any(name in ref for ref in tests))

    def test_platform_images_are_immutable_and_in_inventory(self):
        pins = COMPONENTS["LOCK"]["images"]
        inventory = set(SECURITY["external_images"](ROOT))
        self.assertTrue(set(pins.values()) <= inventory)
        for reference in inventory:
            self.assertRegex(reference, r"@sha256:[0-9a-f]{64}$")
        rendered = COMPONENTS["pin_images"]({"spec": {"containers": [
            {"image": "xpkg.crossplane.io/crossplane/crossplane:v2.4.4"}]}})
        self.assertIn("@sha256:", rendered["spec"]["containers"][0]["image"])

    def test_provisioner_creates_pinned_runtime_images(self):
        result = COMPONENTS["pin_images"]({"args": ["gateway-provisioner"],
            "image": "ghcr.io/projectcontour/contour:v1.33.8"})
        for prefix in ("--contour-image=", "--envoy-image="):
            self.assertTrue(any(arg.startswith(prefix) and "@sha256:" in arg for arg in result["args"]))

    def test_crd_argument_schema_remains_valid(self):
        schema = {"properties": {"args": {"type": "array", "items": {"type": "string"}}}}
        self.assertEqual(COMPONENTS["pin_images"](schema), schema)

    def test_empty_yaml_documents_do_not_reach_kubectl(self):
        result = subprocess.run([sys.executable, str(ROOT / "scripts/components.py")],
                                input="---\napiVersion: v1\nkind: Namespace\nmetadata: {name: test-input}\n---\n",
                                capture_output=True, text=True, check=True)
        self.assertNotIn("null", result.stdout)
        self.assertEqual(result.stdout.count("kind: Namespace"), 1)

    def test_unlisted_platform_image_is_rejected(self):
        for image in ("example.test/new:1.0", "example.test/new", "example.test/new@sha256:invalid"):
            with self.subTest(image=image), self.assertRaisesRegex(ValueError, "Unpinned platform image"):
                COMPONENTS["pin_images"]({"image": image})
        result = subprocess.run([sys.executable, str(ROOT / "scripts/components.py")],
                                input="apiVersion: v1\nkind: Namespace\nmetadata: {name: test-input}\n---\nimage: example.test/new:1.0\n",
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_candidate_rejects_unsupported_profile(self):
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary) / "test.xpkg"
            package.write_bytes(b"test")
            result = subprocess.run(["bash", str(ROOT / "tests/integration/run.bash"), "verify-valkey",
                                     "--kind", "--candidate", str(package), "--check"],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn("requires all on Kind", result.stderr)

    def test_changed_download_is_rejected_before_installation(self):
        with tempfile.TemporaryDirectory() as temporary:
            namespace = COMPONENTS["artifact"].__globals__
            lock = {"artifacts": {"test": {"filename": "test.yaml", "url": "https://example.test/input",
                     "sha256": hashlib.sha256(b"checked").hexdigest()}}}
            import io
            with patch.dict(namespace, ROOT=Path(temporary), LOCK=lock), patch(
                    "urllib.request.urlopen", return_value=io.BytesIO(b"changed")):
                with self.assertRaisesRegex(ValueError, "Checksum mismatch"):
                    COMPONENTS["artifact"]("test")
                self.assertFalse((Path(temporary) / "build/components/test.yaml").exists())


if __name__ == "__main__":
    unittest.main()
