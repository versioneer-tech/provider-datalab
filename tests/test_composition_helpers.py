# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Check random credentials, stored values, and service name separation."""

import ast
import base64
import secrets
import unittest

from helpers import HELPER_SOURCE, load_helpers


class HelperTests(unittest.TestCase):
    def token(self, stored=None, old=None):
        namespace = load_helpers("_b64get_any")
        namespace.update(secrets=secrets, require_secret=lambda *args: stored or {})
        tree = ast.parse(HELPER_SOURCE)
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_service_token")
        exec(ast.get_source_segment(HELPER_SOURCE, function), namespace)
        return namespace["_service_token"](None, None, "test-auth", "test-auth", "test-team", old=old)

    def test_new_credentials_have_independent_random_entropy(self):
        first, second = self.token(), self.token()
        self.assertNotEqual(first, second)
        self.assertGreaterEqual(len(first), 40)
        self.assertEqual(len(base64.urlsafe_b64decode(first + "=")), 32)

    def test_reconciliation_retains_a_stored_password(self):
        stored = {"data": {"password": base64.b64encode(b"test-random-password").decode()}}
        self.assertEqual(self.token(stored), "test-random-password")

    def test_public_name_hash_is_replaced(self):
        old = load_helpers("_name_hash")["_name_hash"]("test-team:registry", length=28)
        stored = {"data": {"password": base64.b64encode(old.encode()).decode()}}
        self.assertNotEqual(self.token(stored, old), old)

    def test_store_names_cannot_target_built_in_or_other_service_types(self):
        name = load_helpers("_store_resource_name")["_store_resource_name"]
        for store in ("registry", "package-r", "vcluster-vc0", "a" * 63):
            with self.subTest(store=store):
                valkey, postgres = name("valkey", store), name("postgres", store)
                self.assertTrue(valkey.startswith("valkey-"))
                self.assertTrue(postgres.startswith("postgres-"))
                self.assertNotEqual(valkey, postgres)
                self.assertNotEqual(valkey, store)
                self.assertLessEqual(len(valkey), 40)


if __name__ == "__main__":
    unittest.main()
