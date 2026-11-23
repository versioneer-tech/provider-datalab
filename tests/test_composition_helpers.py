# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Check backup sizes and stable service credentials."""

import unittest

from helpers import load_helpers


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

    def test_service_tokens_are_stable_and_separate(self):
        token = load_helpers("_strong_token")["_strong_token"]
        mongo = token("test-team:mongo")
        self.assertEqual(mongo, token("test-team:mongo"))
        self.assertNotEqual(mongo, token("test-team:redis"))
        self.assertNotEqual(mongo, token("test-other-team:mongo"))
        self.assertEqual(len(token("test-team:redis", suffix="", length=28)), 28)


if __name__ == "__main__":
    unittest.main()
