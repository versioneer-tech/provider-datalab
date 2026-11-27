#!/usr/bin/env python3
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Check PostgreSQL users, credential rotation, native cold snapshots and recovery."""

import argparse
import base64
from copy import deepcopy
import json
import secrets
import subprocess
import time

NAMESPACE = 'verify-postgres'
LABEL = 'cnpg.io/scheduled-backup'


def wait_for(check, message, timeout=900):
    deadline = time.monotonic() + timeout
    while True:
        value = check()
        if value:
            return value
        if time.monotonic() >= deadline:
            raise AssertionError(message)
        time.sleep(3)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kubeconfig', required=True)
    parser.add_argument('--context', required=True)
    parser.add_argument('--skip-snapshots', action='store_true')
    args = parser.parse_args()
    command = ['kubectl', '--kubeconfig', args.kubeconfig, '--context', args.context]

    def kube(*arguments, body=None, namespace=NAMESPACE, timeout=60, allowed_exit=(0,)):
        result = subprocess.run([*command, '--namespace', namespace, *arguments],
                                input=json.dumps(body) if body is not None else None,
                                text=True, capture_output=True, timeout=timeout)
        if result.returncode not in allowed_exit:
            raise AssertionError('PostgreSQL check failed: ' + ' '.join(arguments[:2]))
        return result.stdout.strip()

    def get(resource, namespace=NAMESPACE):
        value = kube('get', resource, '--ignore-not-found', '-o', 'json', namespace=namespace)
        return json.loads(value) if value else None

    def sql(cluster, query):
        pod = get('cluster.postgresql.cnpg.io/' + cluster)['status']['currentPrimary']
        return kube('exec', pod, '-c', 'postgres', '--', 'psql', '-d', 'verify',
                    '-v', 'ON_ERROR_STOP=1', '-tAc', query)

    def cluster_ready(name):
        cluster = get('cluster.postgresql.cnpg.io/' + name)
        fenced = (cluster or {}).get('metadata', {}).get('annotations', {}).get('cnpg.io/fencedInstances', '[]')
        return cluster and fenced == '[]' and any(c['type'] == 'Ready' and c['status'] == 'True'
                               for c in cluster.get('status', {}).get('conditions', []))

    assert sql('postgres-pg0', "SELECT count(*) FROM pg_database WHERE datname IN ('verify','reporting') AND pg_get_userbyid(datdba) = 'postgres'") == '2'
    sql('postgres-pg0', 'CREATE EXTENSION IF NOT EXISTS postgis')
    assert sql('postgres-pg0', 'SELECT ST_AsText(ST_Point(1,2))') == 'POINT(1 2)'
    print('PASS multiple databases, PostgreSQL ownership, and PostGIS SQL', flush=True)
    declared = json.loads(kube('get', 'databases.postgresql.cnpg.io', '-o', 'json'))['items']
    reporting = next(entry['metadata']['name'] for entry in declared
                     if entry['spec']['name'] == 'reporting' and entry['spec']['cluster']['name'] == 'postgres-pg0')
    kube('patch', 'datalab/verify-postgres', '--type=merge', '--patch',
         '{"spec":{"stores":{"pg0":{"names":["verify"]}}}}', namespace='workspace')
    wait_for(lambda: get('database.postgresql.cnpg.io/' + reporting) is None,
             'Removing a logical name did not remove its declaration')
    assert sql('postgres-pg0', "SELECT count(*) FROM pg_database WHERE datname='reporting'") == '1'
    kube('patch', 'datalab/verify-postgres', '--type=merge', '--patch',
         '{"spec":{"stores":{"pg0":{"names":["verify","reporting"]}}}}', namespace='workspace')
    wait_for(lambda: (get('database.postgresql.cnpg.io/' + reporting) or {}).get('status', {}).get('applied'),
             'The retained logical database was not adopted again')
    print('PASS removing and restoring a logical name retains its PostgreSQL database', flush=True)

    cluster = get('cluster.postgresql.cnpg.io/postgres-pg0')
    role = next(role for role in cluster['spec']['managed']['roles'] if role['name'] == 'verify-s3')
    user_secret = role['passwordSecret']['name']
    wait_for(lambda: get('secret/' + user_secret), 'The user password Secret was not created')
    pod = {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': 'test-postgres-user', 'namespace': NAMESPACE},
           'spec': {'restartPolicy': 'Never', 'automountServiceAccountToken': False,
                    'containers': [{'name': 'check', 'image': 'ghcr.io/cloudnative-pg/postgis:17.12-3.7.0-202611231010-standard-trixie@sha256:b053a93d0687b4ee85418447ffb0a9436461c72efef2e316012728b34f2e50cf',
                                    'env': [{'name': key, 'value': value} for key, value in
                                            [('PGHOST', 'postgres-pg0-rw'), ('PGPORT', '5432'), ('PGDATABASE', 'postgres'),
                                             ('PGSSLMODE', 'require'), ('PGCONNECT_TIMEOUT', '15')]] + [
                                        {'name': key, 'valueFrom': {'secretKeyRef': {'name': user_secret, 'key': field}}}
                                        for key, field in [('PGUSER', 'username'), ('PGPASSWORD', 'password')]],
                                    'command': ['sh', '-ec', 'psql -v ON_ERROR_STOP=1 -tAc "select current_user" >/dev/null 2>&1'],
                                    'resources': {'requests': {'cpu': '20m', 'memory': '32Mi'},
                                                  'limits': {'cpu': '100m', 'memory': '128Mi'}}}]}}
    kube('apply', '-f', '-', body=pod)
    kube('wait', 'pod/test-postgres-user', '--for=condition=PodScheduled', '--timeout=5m', timeout=330)
    wait_for(lambda: get('pod/test-postgres-user')['status'].get('phase') in ('Succeeded', 'Failed'),
             'The named user login probe did not finish')
    assert get('pod/test-postgres-user')['status']['phase'] == 'Succeeded', 'The named user could not authenticate'
    original_user_password = get('secret/' + user_secret)['data']['password']
    print('PASS named PostgreSQL user authenticates with its own password over TLS', flush=True)

    native = get('secret/postgres-pg0-superuser')
    password = base64.b64encode((secrets.token_urlsafe(32) + '@:/?%#').encode()).decode()
    native['data']['password'] = password
    native['metadata'].setdefault('labels', {})['cnpg.io/reload'] = 'true'
    # Send credential changes on stdin, without logging their values.
    kube('replace', '-f', '-', body=native)
    wait_for(lambda: get('secret/verify-postgres-postgres-pg0', namespace='workspace')['data'].get('password') == password,
             'Published PostgreSQL credentials did not rotate')
    assert get('secret/' + user_secret)['data']['password'] == original_user_password
    admin_probe = deepcopy(pod)
    admin_probe['metadata'] = {'name': 'test-postgres-admin-rotation', 'namespace': 'workspace',
                               'labels': {'app.kubernetes.io/name': 'datalab-service-probe'}}
    admin_probe['spec']['activeDeadlineSeconds'] = 300
    admin_container = admin_probe['spec']['containers'][0]
    admin_container['env'] = [
        {'name': 'PGSSLMODE', 'value': 'require'}, {'name': 'PGCONNECT_TIMEOUT', 'value': '5'},
        {'name': 'POSTGRES_URL', 'valueFrom': {'secretKeyRef': {
            'name': 'verify-postgres-postgres-pg0', 'key': 'verify_url'}}},
    ]
    admin_container['command'] = ['sh', '-ec',
        'attempt=0; until psql "$POSTGRES_URL" -v ON_ERROR_STOP=1 -tAc "select current_user" >/dev/null 2>&1; '
        'do attempt=$((attempt + 1)); test "$attempt" -lt 60 || exit 1; sleep 2; done']
    kube('apply', '-f', '-', body=admin_probe, namespace='workspace')
    kube('wait', 'pod/test-postgres-admin-rotation', '--for=condition=PodScheduled', '--timeout=5m',
         namespace='workspace', timeout=330)
    wait_for(lambda: get('pod/test-postgres-admin-rotation', namespace='workspace')['status'].get('phase')
             in ('Succeeded', 'Failed'), 'The rotated administrator login probe did not finish', timeout=360)
    assert get('pod/test-postgres-admin-rotation', namespace='workspace')['status']['phase'] == 'Succeeded', \
        'The rotated connection Secret could not authenticate'
    kube('delete', 'pod/test-postgres-admin-rotation', '--wait=true', namespace='workspace')
    print('PASS rotated connection credentials authenticate over TLS and retain user passwords', flush=True)
    if args.skip_snapshots:
        return

    schedule = get('scheduledbackup.postgresql.cnpg.io/postgres-snapshot-pg0')
    assert schedule['spec']['schedule'] == '0 0 1 * * *'
    assert schedule['spec']['method'] == 'volumeSnapshot' and schedule['spec']['online'] is False
    assert schedule['spec']['backupOwnerReference'] == 'cluster'
    assert schedule.get('status', {}).get('lastCheckTime') and not schedule['status'].get('error')
    assert get('cronjob/postgres-snapshot-pg0') is None
    print('PASS native daily cold schedule needs no PostgreSQL backup Job', flush=True)

    def backups():
        return json.loads(kube('get', 'backups.postgresql.cnpg.io', '-l',
                               LABEL + '=test-pg-scheduled', '-o', 'json'))['items']

    sql('postgres-pg0', "INSERT INTO provider_datalab_verify(id,value) VALUES('recovery','snapshot-value') ON CONFLICT(id) DO UPDATE SET value=excluded.value")
    immediate = {'apiVersion': 'postgresql.cnpg.io/v1', 'kind': 'ScheduledBackup',
                 'metadata': {'name': 'test-pg-scheduled', 'namespace': NAMESPACE},
                 'spec': {**deepcopy(schedule['spec']), 'immediate': True}}
    kube('apply', '-f', '-', body=immediate)
    recovery = wait_for(lambda: next((entry for entry in backups()
                        if entry.get('status', {}).get('phase') == 'completed'), None),
                        'The native ScheduledBackup did not complete')
    assert recovery['spec']['method'] == 'volumeSnapshot' and recovery['spec']['online'] is False
    assert any(owner['kind'] == 'Cluster' and owner['uid'] == cluster['metadata']['uid']
               for owner in recovery['metadata'].get('ownerReferences', []))
    snapshot = next(entry['name'] for entry in recovery['status']['snapshotBackupStatus']['elements']
                    if entry['type'] == 'PG_DATA')
    snapshot_resource = get('volumesnapshot/' + snapshot)
    assert snapshot_resource['status']['readyToUse'] is True
    assert any(owner['kind'] == 'Backup' and owner['uid'] == recovery['metadata']['uid']
               for owner in snapshot_resource['metadata'].get('ownerReferences', []))
    wait_for(lambda: cluster_ready('postgres-pg0'), 'The primary did not resume after its cold backup')
    kube('delete', 'scheduledbackup.postgresql.cnpg.io/test-pg-scheduled', '--wait=true')
    assert get('backup.postgresql.cnpg.io/' + recovery['metadata']['name'])
    print('PASS native scheduling creates a ready cold snapshot and resumes PostgreSQL', flush=True)
    sql('postgres-pg0', "UPDATE provider_datalab_verify SET value='source-after-backup' WHERE id='recovery'")
    restore_storage = deepcopy(cluster['spec']['storage'])
    restore_storage['size'] = snapshot_resource['status'].get('restoreSize') or restore_storage['size']
    restore = {'apiVersion': 'postgresql.cnpg.io/v1', 'kind': 'Cluster',
               'metadata': {'name': 'test-pg-recovery', 'namespace': NAMESPACE},
               'spec': {'instances': 1, 'imageName': cluster['spec']['imageName'],
                        'enableSuperuserAccess': True, 'storage': restore_storage,
                        'bootstrap': {'recovery': {'database': 'verify', 'owner': 'datalab',
                            'volumeSnapshots': {'storage': {'name': snapshot, 'kind': 'VolumeSnapshot',
                                                           'apiGroup': 'snapshot.storage.k8s.io'}}}}}}
    # Recovery also needs the managed cluster's operator health access.
    network = {'apiVersion': 'networking.k8s.io/v1', 'kind': 'NetworkPolicy',
               'metadata': {'name': 'test-pg-recovery', 'namespace': NAMESPACE},
               'spec': deepcopy(get('networkpolicy/postgres-pg0')['spec'])}
    network['spec']['podSelector'] = {'matchLabels': {'cnpg.io/cluster': 'test-pg-recovery'}}
    kube('apply', '-f', '-', body=network)
    kube('apply', '-f', '-', body=restore)
    wait_for(lambda: cluster_ready('test-pg-recovery'), 'Snapshot restore cluster did not become Ready')
    assert sql('test-pg-recovery', "SELECT value FROM provider_datalab_verify WHERE id='recovery'") == 'snapshot-value'
    sql('test-pg-recovery', "UPDATE provider_datalab_verify SET value='restored-only' WHERE id='recovery'")
    assert sql('postgres-pg0', "SELECT value FROM provider_datalab_verify WHERE id='recovery'") == 'source-after-backup'
    print('PASS snapshot restore recovers the database contents and writes independently', flush=True)
    retained = {entry['metadata']['uid'] for entry in backups()}
    kube('patch', 'datalab/verify-postgres', '--type=merge', '--patch',
         '{"spec":{"stores":{"pg0":{"backups":false}}}}', namespace='workspace')
    wait_for(lambda: get('scheduledbackup.postgresql.cnpg.io/postgres-snapshot-pg0') is None, 'Disabling PostgreSQL backups did not remove its schedule')
    assert {entry['metadata']['uid'] for entry in backups()} == retained
    assert sql('test-pg-recovery', "SELECT value FROM provider_datalab_verify WHERE id='recovery'") == 'restored-only'
    kube('delete', 'cluster.postgresql.cnpg.io/test-pg-recovery', '--wait=true', '--timeout=5m', timeout=330)
    kube('delete', 'networkpolicy/test-pg-recovery', '--wait=false')
    print('PASS disabling PostgreSQL backups retains completed recovery points', flush=True)
    # Kyverno retention deletes Backup objects; their owned snapshots follow.
    kube('delete', 'backup.postgresql.cnpg.io/' + recovery['metadata']['name'], '--wait=true')
    wait_for(lambda: get('volumesnapshot/' + snapshot) is None,
             'Deleting a completed Backup did not remove its owned snapshot')
    assert sql('postgres-pg0', "SELECT value FROM provider_datalab_verify WHERE id='recovery'") == 'source-after-backup'
    print('PASS Backup deletion removes its snapshot and preserves the source database', flush=True)



if __name__ == '__main__':
    main()
