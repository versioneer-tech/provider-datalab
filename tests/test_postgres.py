# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Check PostgreSQL recovery-point retention and connection credentials."""

import base64
from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
import runpy
import unittest

from helpers import ROOT, load_helpers


class PostgresSnapshotTests(unittest.TestCase):
    def run_backup(self, *, phase='completed', ready=True, owner=True, replaced=False, policy='Delete', pending=False):
        module = runpy.run_path(str(ROOT / 'scripts/postgres-snapshot.py'))
        label, source = module['LABEL'], module['SOURCE']
        calls = []
        reads = 0

        def item(name, cluster='pg0', uid='cluster-current', state='completed'):
            return {'metadata': {'name': name, 'uid': name + '-uid', 'creationTimestamp': name,
                                 'labels': {label: cluster, source: uid}},
                    'spec': {'cluster': {'name': cluster}, 'method': 'volumeSnapshot', 'online': False},
                    'status': {'phase': state, 'snapshotBackupStatus': {
                        'elements': [{'name': name + '-snapshot', 'type': 'PG_DATA'}]}}}

        backups = {entry['metadata']['name']: entry for entry in (
            item('20261120'), item('20261121'), item('another', cluster='pg1'), item('replaced', uid='cluster-old'))}
        if pending:
            backups['20261122'] = item('20261122', state='running')

        class API:
            def call(self, method, path, body=None):
                nonlocal reads
                calls.append((method, path, deepcopy(body)))
                if '/volumesnapshotclasses/' in path:
                    return {'deletionPolicy': policy}
                if '/clusters/' in path:
                    reads += 1
                    return {'metadata': {'uid': 'cluster-other' if replaced and reads > 1 else 'cluster-current'},
                            'spec': {'backup': {'volumeSnapshot': {
                                'className': 'snapshots', 'online': False, 'snapshotOwnerReference': 'backup'}}}}
                if '/volumesnapshots/' in path:
                    name = path.rsplit('/', 1)[-1].removesuffix('-snapshot')
                    return {'metadata': {'ownerReferences': [{'kind': 'Backup', 'uid': name + '-uid' if owner else 'foreign'}]},
                            'status': {'readyToUse': ready}}
                if method == 'POST':
                    created = item('20261122', state=phase)
                    backups['20261122'] = created
                    return created
                if method == 'DELETE':
                    name = path.rsplit('/', 1)[-1]
                    assert body['preconditions']['uid'] == backups[name]['metadata']['uid']
                    del backups[name]
                    return {}
                if '?' in path:
                    return {'items': list(backups.values())}
                return backups[path.rsplit('/', 1)[-1]]

        failure = None
        with redirect_stdout(StringIO()):
            try:
                module['backup'](API(), 'team', 'pg0', 'snapshots', 1, timeout=0)
            except RuntimeError as error:
                failure = error
        return backups, calls, failure

    def test_retention_preserves_other_clusters_and_previous_cluster_identity(self):
        backups, calls, failure = self.run_backup()
        self.assertIsNone(failure)
        self.assertEqual(set(backups), {'20261122', 'another', 'replaced'})

    def test_failures_do_not_remove_completed_recovery_points(self):
        for options in ({'phase': 'failed'}, {'phase': 'running'}, {'ready': False}, {'owner': False}, {'replaced': True}):
            with self.subTest(options=options):
                backups, calls, failure = self.run_backup(**options)
                self.assertIsNotNone(failure)
                self.assertIn('20261120', backups)
                self.assertFalse(any(method == 'DELETE' for method, _, _ in calls))

    def test_retry_waits_for_the_existing_backup(self):
        backups, calls, failure = self.run_backup(pending=True)
        self.assertIsNotNone(failure)
        self.assertFalse(any(method == 'POST' for method, _, _ in calls))
        self.assertIn('20261120', backups)

    def test_retained_snapshot_storage_is_rejected(self):
        backups, calls, failure = self.run_backup(policy='Retain')
        self.assertIn('deletion policy Delete', str(failure))
        self.assertFalse(any(method in ('POST', 'DELETE') for method, _, _ in calls))

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
