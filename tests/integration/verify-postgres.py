#!/usr/bin/env python3
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Check PostgreSQL users, credential rotation, snapshot retention, and recovery."""

import argparse
import base64
from copy import deepcopy
import json
import secrets
import subprocess
import time

NAMESPACE = 'verify-postgres'
LABEL = 'datalabs.versioneer.at/postgres-backup'


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

    assert sql('pg0', "SELECT count(*) FROM pg_database WHERE datname IN ('verify','reporting') AND pg_get_userbyid(datdba) = 'postgres'") == '2'
    sql('pg0', 'CREATE EXTENSION IF NOT EXISTS postgis')
    assert sql('pg0', 'SELECT ST_AsText(ST_Point(1,2))') == 'POINT(1 2)'
    print('PASS multiple databases, PostgreSQL ownership, and PostGIS SQL', flush=True)
    declared = json.loads(kube('get', 'databases.postgresql.cnpg.io', '-o', 'json'))['items']
    reporting = next(entry['metadata']['name'] for entry in declared
                     if entry['spec']['name'] == 'reporting' and entry['spec']['cluster']['name'] == 'pg0')
    kube('patch', 'datalab/verify-postgres', '--type=merge', '--patch',
         '{"spec":{"stores":{"pg0":{"names":["verify"]}}}}', namespace='workspace')
    wait_for(lambda: get('database.postgresql.cnpg.io/' + reporting) is None,
             'Removing a logical name did not remove its declaration')
    assert sql('pg0', "SELECT count(*) FROM pg_database WHERE datname='reporting'") == '1'
    kube('patch', 'datalab/verify-postgres', '--type=merge', '--patch',
         '{"spec":{"stores":{"pg0":{"names":["verify","reporting"]}}}}', namespace='workspace')
    wait_for(lambda: (get('database.postgresql.cnpg.io/' + reporting) or {}).get('status', {}).get('applied'),
             'The retained logical database was not adopted again')
    print('PASS removing and restoring a logical name retains its PostgreSQL database', flush=True)

    cluster = get('cluster.postgresql.cnpg.io/pg0')
    role = next(role for role in cluster['spec']['managed']['roles'] if role['name'] == 'verify-s3')
    user_secret = role['passwordSecret']['name']
    wait_for(lambda: get('secret/' + user_secret), 'The user password Secret was not created')
    pod = {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': 'test-postgres-user', 'namespace': NAMESPACE},
           'spec': {'restartPolicy': 'Never', 'automountServiceAccountToken': False,
                    'containers': [{'name': 'check', 'image': 'postgres:17',
                                    'env': [{'name': key, 'value': value} for key, value in
                                            [('PGHOST', 'pg0-rw'), ('PGPORT', '5432'), ('PGDATABASE', 'postgres'),
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

    native = get('secret/pg0-superuser')
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

    kube('patch', 'environmentconfig/datalab', '--type=merge', '--patch',
         '{"data":{"database":{"maxSnapshots":2}}}', namespace='workspace')
    wait_for(lambda: (get('cronjob/postgres-snapshot-pg0') or {}).get('spec', {}).get('jobTemplate', {})
             .get('spec', {}).get('template', {}).get('spec', {}).get('containers', [{}])[0].get('args', [])[-1:] == ['2'],
             'The PostgreSQL retention setting was not applied')
    cronjob = get('cronjob/postgres-snapshot-pg0')
    identity = 'system:serviceaccount:' + NAMESPACE + ':' + cronjob['spec']['jobTemplate']['spec']['template']['spec']['serviceAccountName']
    for verb, resource, expected in [('create', 'backups.postgresql.cnpg.io', 'yes'),
                                      ('delete', 'backups.postgresql.cnpg.io', 'yes'),
                                      ('get', 'clusters.postgresql.cnpg.io/pg0', 'yes'),
                                      ('get', 'clusters.postgresql.cnpg.io/pg1', 'no'),
                                      ('list', 'secrets', 'no'), ('delete', 'persistentvolumeclaims', 'no'),
                                      ('delete', 'volumesnapshots.snapshot.storage.k8s.io', 'no')]:
        assert kube('auth', 'can-i', verb, resource, '--as', identity, allowed_exit=(0, 1)) == expected
    print('PASS PostgreSQL backup identity has no Secret or PVC deletion access', flush=True)

    def backups():
        return json.loads(kube('get', 'backups.postgresql.cnpg.io', '-l', LABEL + '=pg0', '-o', 'json'))['items']

    def run_backup(fail=False):
        job = deepcopy(cronjob['spec']['jobTemplate'])
        job.update(apiVersion='batch/v1', kind='Job', metadata={'generateName': 'test-postgres-backup-'})
        if fail:
            job['spec']['backoffLimit'] = 0
            job['spec']['template']['spec']['containers'][0]['args'][2] = 'test-missing-snapshot-class'
        created = json.loads(kube('create', '-f', '-', '-o', 'json', body=job))
        job_name = created['metadata']['name']
        pods = wait_for(lambda: json.loads(kube('get', 'pods', '-l', 'batch.kubernetes.io/job-name=' + job_name,
                                               '-o', 'json'))['items'], 'The backup Job did not create a Pod', timeout=120)
        kube('wait', 'pod/' + pods[0]['metadata']['name'], '--for=condition=PodScheduled', '--timeout=5m', timeout=330)
        def finished():
            conditions = get('job/' + job_name).get('status', {}).get('conditions', [])
            for condition in conditions:
                if condition['status'] == 'True' and condition['type'] in ('Complete', 'Failed'):
                    assert condition['type'] == ('Failed' if fail else 'Complete'), 'Unexpected backup Job outcome: ' + job_name
                    return True
            return False
        try:
            wait_for(finished, 'PostgreSQL snapshot Job did not finish')
        except AssertionError:
            print(kube('logs', 'job/' + job_name, '--all-containers=true'), flush=True)
            raise
        wait_for(lambda: cluster_ready('pg0'), 'The primary did not resume after its cold backup')
        return backups()

    sql('pg0', "INSERT INTO provider_datalab_verify(id,value) VALUES('recovery','first') ON CONFLICT(id) DO UPDATE SET value=excluded.value")
    first = run_backup()
    first_uid = first[0]['metadata']['uid']
    first_snapshots = [entry['name'] for entry in first[0]['status']['snapshotBackupStatus']['elements']]
    before = {entry['metadata']['uid'] for entry in first}
    run_backup(fail=True)
    assert {entry['metadata']['uid'] for entry in backups()} == before
    sql('pg0', "UPDATE provider_datalab_verify SET value='snapshot-value' WHERE id='recovery'")
    run_backup()
    completed = run_backup()
    wait_for(lambda: len(backups()) == 2, 'Snapshot retention did not keep two backups')
    assert first_uid not in {entry['metadata']['uid'] for entry in backups()}
    wait_for(lambda: all(get('volumesnapshot/' + name) is None for name in first_snapshots),
             'Retention did not remove the expired volume snapshots')
    recovery = max(completed, key=lambda entry: entry['metadata']['creationTimestamp'])
    snapshot = next(entry['name'] for entry in recovery['status']['snapshotBackupStatus']['elements'] if entry['type'] == 'PG_DATA')
    snapshot_resource = get('volumesnapshot/' + snapshot)
    assert snapshot_resource['status']['readyToUse'] is True
    print('PASS cold snapshot backups resume PostgreSQL; failures preserve backups; retention keeps two', flush=True)
    sql('pg0', "UPDATE provider_datalab_verify SET value='source-after-backup' WHERE id='recovery'")
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
               'spec': deepcopy(get('networkpolicy/pg0')['spec'])}
    network['spec']['podSelector'] = {'matchLabels': {'cnpg.io/cluster': 'test-pg-recovery'}}
    kube('apply', '-f', '-', body=network)
    kube('apply', '-f', '-', body=restore)
    wait_for(lambda: cluster_ready('test-pg-recovery'), 'Snapshot restore cluster did not become Ready')
    assert sql('test-pg-recovery', "SELECT value FROM provider_datalab_verify WHERE id='recovery'") == 'snapshot-value'
    sql('test-pg-recovery', "UPDATE provider_datalab_verify SET value='restored-only' WHERE id='recovery'")
    assert sql('pg0', "SELECT value FROM provider_datalab_verify WHERE id='recovery'") == 'source-after-backup'
    print('PASS snapshot restore recovers the database contents and writes independently', flush=True)
    retained = {entry['metadata']['uid'] for entry in backups()}
    kube('patch', 'datalab/verify-postgres', '--type=merge', '--patch',
         '{"spec":{"stores":{"pg0":{"backups":false}}}}', namespace='workspace')
    wait_for(lambda: get('cronjob/postgres-snapshot-pg0') is None, 'Disabling PostgreSQL backups did not remove its schedule')
    assert {entry['metadata']['uid'] for entry in backups()} == retained
    assert sql('test-pg-recovery', "SELECT value FROM provider_datalab_verify WHERE id='recovery'") == 'restored-only'
    kube('delete', 'cluster.postgresql.cnpg.io/test-pg-recovery', '--wait=true', '--timeout=5m', timeout=330)
    kube('delete', 'networkpolicy/test-pg-recovery', '--wait=false')
    kube('patch', 'environmentconfig/datalab', '--type=merge', '--patch',
         '{"data":{"database":{"maxSnapshots":null}}}', namespace='workspace')
    print('PASS disabling PostgreSQL backups retains completed recovery points', flush=True)


if __name__ == '__main__':
    main()
