# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Check PostgreSQL connection credentials."""

import base64
import unittest

from helpers import load_helpers


class PostgresConnectionTests(unittest.TestCase):
    def test_connection_normalization_encodes_credentials_and_uses_the_shared_service(self):
        normalize = load_helpers('_postgres_connection_data')['_postgres_connection_data']
        values = {'username': 'postgres', 'password': 'test:@/?# password', 'dbname': 'app/db'}
        encoded = {key: base64.b64encode(value.encode()).decode() for key, value in values.items()}
        data = {key: base64.b64decode(value).decode() for key, value in normalize(encoded, 'pg0', 'team').items()}
        self.assertEqual(data['host'], 'pg0-rw.team.svc')
        self.assertEqual(data['uri'], 'postgresql://postgres:test%3A%40%2F%3F%23%20password@pg0-rw.team.svc:5432/app%2Fdb')
        encoded.pop('password')
        self.assertEqual(normalize(encoded, 'pg0', 'team'), {})


if __name__ == '__main__':
    unittest.main()
