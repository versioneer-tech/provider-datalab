# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Check stable service credentials."""

import unittest

from helpers import load_helpers


class HelperTests(unittest.TestCase):
    def test_service_tokens_are_stable_and_separate(self):
        token = load_helpers("_strong_token")["_strong_token"]
        registry = token("test-team:registry")
        self.assertEqual(registry, token("test-team:registry"))
        self.assertNotEqual(registry, token("test-team:valkey"))
        self.assertNotEqual(registry, token("test-other-team:registry"))
        self.assertEqual(len(token("test-team:valkey", suffix="", length=28)), 28)


if __name__ == "__main__":
    unittest.main()
