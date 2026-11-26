#!/usr/bin/env python3
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Check probes and readiness on the deployed long-running containers."""

import argparse
import json
import subprocess
import time

parser = argparse.ArgumentParser(description=__doc__)
for name in ('kubeconfig', 'context', 'namespace'):
    parser.add_argument('--' + name, required=True)
args = parser.parse_args()
command = ['kubectl', '--kubeconfig', args.kubeconfig, '--context', args.context,
           'get', 'pods', '--namespace', args.namespace, '-o', 'json']
deadline = time.monotonic() + 600
attempt = 0
while True:
    pods = json.loads(subprocess.check_output(command, text=True, timeout=30))['items']
    pods = [pod for pod in pods if pod['spec'].get('restartPolicy', 'Always') == 'Always'
            and not pod['metadata'].get('deletionTimestamp')]
    pending = []
    for pod in pods:
        statuses = {item['name']: item for item in pod.get('status', {}).get('containerStatuses', [])}
        for container in pod['spec']['containers']:
            name = pod['metadata']['name'] + '/' + container['name']
            for probe in ('readinessProbe', 'livenessProbe'):
                if probe not in container:
                    pending.append(name + ': missing ' + probe)
            status = statuses.get(container['name'], {})
            if not status.get('ready') or 'running' not in status.get('state', {}):
                pending.append(name)
    if pods and not pending:
        print(f'PASS {args.namespace}: deployed containers have readiness and liveness probes and are ready', flush=True)
        break
    if time.monotonic() >= deadline:
        raise AssertionError('Probed workloads did not become ready: ' + ', '.join(pending or [args.namespace]))
    if attempt % 15 == 0:
        print('Waiting for probed containers: ' + ', '.join(pending or [args.namespace]), flush=True)
    attempt += 1
    time.sleep(2)
