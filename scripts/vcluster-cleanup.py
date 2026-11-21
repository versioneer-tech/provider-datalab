#!/usr/bin/env python3
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Remove an offline instance's host Pods without changing its storage."""

import json
from pathlib import Path
import ssl
import sys
import time
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, build_opener, HTTPSHandler, ProxyHandler


class API:
    def __init__(self):
        self.account = Path('/var/run/secrets/kubernetes.io/serviceaccount')
        self.http = build_opener(
            ProxyHandler({}),
            HTTPSHandler(context=ssl.create_default_context(cafile=str(self.account / 'ca.crt'))),
        )

    def call(self, method, path, body=None):
        # Read the projected token for each request so rotation takes effect.
        headers = {'Authorization': 'Bearer ' + (self.account / 'token').read_text().strip()}
        data = None if body is None else json.dumps(body).encode()
        if data is not None:
            headers['Content-Type'] = 'application/json'
        request = Request('https://kubernetes.default.svc' + path, data=data,
                          headers=headers, method=method)
        try:
            with self.http.open(request, timeout=10) as result:
                return json.load(result)
        except HTTPError as error:
            if error.code == 404:
                return None
            if error.code == 409 and method == 'DELETE':
                return None
            raise RuntimeError(f'Kubernetes {method} {path} failed: HTTP {error.code}') from None


def owned_by(pod, kind, uid):
    return any(owner.get('kind') == kind and owner.get('uid') == uid
               for owner in pod['metadata'].get('ownerReferences', []))


def cleanup_once(api, namespace, runtime, generation):
    core = '/api/v1/namespaces/' + quote(namespace, safe='')
    statefulset = api.call('GET', '/apis/apps/v1/namespaces/' + quote(namespace, safe='')
                          + '/statefulsets/' + quote(runtime, safe=''))
    if not statefulset:
        return False
    target = json.loads(statefulset['metadata'].get('annotations', {}).get(
        'datalabs.versioneer.at/lifecycle-request', '{}'))
    if target.get('generation', 0) > generation or (
            target.get('generation') == generation and not target.get('hibernated')):
        raise RuntimeError('This cleanup request was superseded; no further Pods will be deleted.')
    if target.get('generation') != generation or statefulset['spec'].get('replicas', 1) != 0:
        print('Waiting for control-plane replicas to reach zero.', flush=True)
        return False
    pods = api.call('GET', core + '/pods')['items']
    if any(owned_by(pod, 'StatefulSet', statefulset['metadata']['uid']) for pod in pods):
        print('Waiting for the control-plane Pod to terminate.', flush=True)
        return False
    service = api.call('GET', core + '/services/' + quote(runtime, safe=''))
    if not service:
        raise RuntimeError('The instance Service is missing; Pod ownership cannot be checked.')
    workloads = [pod for pod in pods if owned_by(pod, 'Service', service['metadata']['uid'])]
    # Reject a Pod list that crossed a scale or request change. UID preconditions
    # then protect replacement Pods if resume starts after this second read.
    current = api.call('GET', '/apis/apps/v1/namespaces/' + quote(namespace, safe='')
                       + '/statefulsets/' + quote(runtime, safe=''))
    if (not current or current['metadata']['uid'] != statefulset['metadata']['uid']
            or current['metadata']['generation'] != statefulset['metadata']['generation']
            or current['metadata'].get('annotations', {}).get('datalabs.versioneer.at/lifecycle-request')
            != statefulset['metadata'].get('annotations', {}).get('datalabs.versioneer.at/lifecycle-request')):
        return False
    for pod in workloads:
        if not pod['metadata'].get('deletionTimestamp'):
            name = pod['metadata']['name']
            api.call('DELETE', core + '/pods/' + quote(name, safe=''), {
                'apiVersion': 'v1', 'kind': 'DeleteOptions',
                'preconditions': {'uid': pod['metadata']['uid']},
            })
            print('Deleting synced Pod ' + name, flush=True)
    return not workloads


def main():
    namespace, runtime, generation = sys.argv[1:]
    api = API()
    while not cleanup_once(api, namespace, runtime, int(generation)):
        time.sleep(2)
    print('Hibernation complete: control plane and synced host Pods are gone.', flush=True)


if __name__ == '__main__':
    main()
