#!/usr/bin/env python3
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Render endpoint configurations and check routing and prerequisite failures."""

import argparse
import base64
from copy import deepcopy
import hashlib
import json
import re
from pathlib import Path
import subprocess
import tempfile

import yaml


ENVIRONMENT = {
    'apiVersion': 'apiextensions.crossplane.io/v1beta1',
    'kind': 'EnvironmentConfig',
    'metadata': {'name': 'datalab'},
    'data': {
        'iam': {
            'realm': 'acme',
            'issuerURL': 'https://identity.acme.com/realms/acme',
            'internalURL': 'http://keycloak.keycloak:8080/realms/acme',
        },
        'ingress': {
            'enabled': False,
            'domain': 'lab.acme.com',
        },
        'httpRoute': {
            'enabled': True,
            'enableS3': True,
            'parentName': 'default',
            'parentNamespace': 'contour',
            'sectionName': 'workspaces-https',
            'httpSectionName': 'workspaces-http',
        },
    },
}


def resource(output, name):
    matches = [item for item in output.split('---\n') if f'\n  name: {name}\n' in item]
    assert len(matches) <= 1, name
    return matches[0] if matches else ''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--functions', default='dependencies/functions.yaml')
    parser.add_argument('--network')
    args = parser.parse_args()
    datalab = Path('examples/base/001-lab.yaml').read_text()
    with tempfile.TemporaryDirectory(prefix='data-routing-') as directory:
        work = Path(directory)

        def render(environment, source=datalab, error=None, observed='tests/observed/001-lab.yaml'):
            (work / 'environment.json').write_text(json.dumps(environment))
            (work / 'datalab.yaml').write_text(source)
            result = subprocess.run([
                'crossplane', 'render', str(work / 'datalab.yaml'), 'composition.yaml',
                args.functions, '--required-resources', str(work / 'environment.json'),
                '--observed-resources', observed, '-x',
            ] + (['--crossplane-docker-network', args.network] if args.network else []),
                capture_output=True, text=True, timeout=120)
            if error:
                assert result.returncode != 0, 'Invalid configuration was accepted'
                assert error in result.stderr, result.stderr
            else:
                assert result.returncode == 0, result.stderr
            return result.stdout

        for exposure in ('default', 'gateway', 'gateway-s3', 'disabled-data', 'session'):
            env = deepcopy(ENVIRONMENT)
            ingress = env['data']['ingress']
            route_config = env['data']['httpRoute']
            source = datalab
            if exposure in ('default', 'session'):
                route_config.update({'enabled': False, 'enableS3': False})
                ingress.update({'enabled': exposure == 'default', 'class': 'nginx', 'secret': 'wildcard-tls'})
            if exposure == 'gateway':
                route_config.pop('enableS3')  # S3 defaults to false.
            if exposure == 'disabled-data':
                env['data']['defaults'] = {'data': {'enabled': False}}
            output = render(env, source)
            if exposure == 'default':
                workshop = resource(output, 'workshop-s-joe')
                assert re.search(r'vcluster:\s+enabled: true', workshop)
                assert re.search(r'registry:\s+enabled: true\s+storage: 5Gi', workshop)
            assert bool(resource(output, 'data-ingress-s-joe')) == (exposure in ('default',))
            route = resource(output, 'data-route-s-joe')
            assert bool(route) == (exposure in ('gateway', 'gateway-s3'))
            redirect = resource(output, 'data-redirect-s-joe')
            assert bool(redirect) == bool(route)
            if route:
                assert 'kind: HTTPRoute' in route and 'name: package-r' in route and 'port: 4180' in route
                assert 's-joe.lab.acme.com' in route
                assert 'Accepted' in route and 'ResolvedRefs' in route
                assert 'RequestRedirect' in redirect and 'scheme: https' in redirect
                assert ('name: data-s3' in route) == (exposure in ('gateway-s3',))
            for kind in ('config', 'deployment', 'service', 'networkpolicy'):
                assert bool(resource(output, f'data-s3-{kind}-s-joe')) == (exposure in ('gateway-s3',))
            if exposure == 'gateway-s3':
                policy = resource(output, 'data-s3-networkpolicy-s-joe')
                assert 'egress:' in policy and 'port: 8080' in policy
                assert 'kubernetes.io/metadata.name: keycloak' in policy
            assert ('included.client.audience: s-joe' in output) == (exposure in ('gateway-s3',))
            deployment = resource(output, 'data-deployment-s-joe')
            assert bool(deployment) == (exposure != 'disabled-data')
            if deployment:
                assert "--cors-allowed-origins='*'" in deployment
                assert '--perm.create=true' in deployment
                assert 'name: AWS_SHARED_CREDENTIALS_FILE' in deployment
                assert '/var/run/datalab/storage/aws-credentials' in deployment
                for key in ('AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_SESSION_TOKEN'):
                    assert f'name: {key}' not in deployment
            if exposure in ('default', 'gateway', 'gateway-s3'):
                assert '--client-secret-file=/var/run/datalab/oauth2/client_secret' in deployment
                assert '--cookie-secret-file=/var/run/datalab/oauth2/cookie_secret' in deployment
                assert 'OAUTH2_PROXY_CLIENT_SECRET' not in deployment
                assert 'OAUTH2_PROXY_COOKIE_SECRET' not in deployment
                assert 'name: oauth2-credentials' in deployment
                assert 'subPath:' not in deployment
            if exposure == 'gateway-s3':
                s3_deployment = resource(output, 'data-s3-deployment-s-joe')
                assert '--client-secret-file=/var/run/datalab/oauth2/client_secret' in s3_deployment
                assert 'name: oauth2-credentials' in s3_deployment
                assert 'OAUTH2_PROXY_CLIENT_SECRET' not in s3_deployment
                assert 'name: AWS_SHARED_CREDENTIALS_FILE' in s3_deployment
                for key in ('AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_SESSION_TOKEN'):
                    assert f'name: {key}' not in s3_deployment
            print(f'PASS endpoint configuration: {exposure}', flush=True)

        env = deepcopy(ENVIRONMENT)
        env['data']['iam']['namespace'] = 'identity'
        output = render(env)
        policy = resource(output, 'data-s3-networkpolicy-s-joe')
        assert 'kubernetes.io/metadata.name: identity' in policy
        assert 'kubernetes.io/metadata.name: keycloak' not in policy
        assert 'port: 8080' in policy and '- Egress' in policy
        print('PASS S3 IAM egress in custom namespace', flush=True)

        def oauth_render(secret):
            observer = {
                'apiVersion': 'kubernetes.m.crossplane.io/v1alpha1',
                'kind': 'Object',
                'metadata': {
                    'name': 'observe-oauth-client-secret-s-joe',
                    'annotations': {'crossplane.io/composition-resource-name': 'observe-oauth-client-secret-s-joe'},
                },
                'status': {'atProvider': {'manifest': {'data': {
                    'clientSecret': base64.b64encode(secret.encode()).decode(),
                }}}},
            }
            fixture = work / 'oauth-observed.yaml'
            fixture.write_text(Path('tests/observed/001-lab.yaml').read_text()
                               + '\n---\n' + json.dumps(observer))
            return render(deepcopy(ENVIRONMENT), observed=str(fixture))

        first = oauth_render('initial-client-secret')
        second = oauth_render('rotated-client-secret')
        for output, secret in ((first, 'initial-client-secret'), (second, 'rotated-client-secret')):
            projected = yaml.safe_load(resource(output, 'oauth2-client-secret-s-joe'))['spec']['forProvider']['manifest']
            assert 'stringData' not in projected
            decoded = {key: base64.b64decode(value).decode() for key, value in projected['data'].items()}
            assert decoded == {
                'client_id': 's-joe',
                'client_secret': secret,
                'cookie_secret': hashlib.sha256(secret.encode()).hexdigest()[:32],
            }
            generated = resource(output, 's-joe-datalab')
            assert 'OAUTH2_CLIENT_ID: s-joe' in generated
            assert f'OAUTH2_CLIENT_SECRET: {secret}' in generated
            assert 'aws-credentials: |' in generated
            assert '[default]' in generated
            assert 'aws_access_key_id = ' in generated
            assert 'aws_secret_access_key = ' in generated
        for name in ('data-deployment-s-joe', 'data-s3-deployment-s-joe'):
            def checksum(output):
                return re.search(r'oauth2-cookie-checksum: (\S+)', resource(output, name)).group(1)
            assert checksum(first) != checksum(second)
        print('PASS OAuth credentials and cookie rotation rollout', flush=True)

        cases = [
            ('both-endpoints', ('ingress', 'enabled'), True, 'Enable only one'),
            ('s3-without-route', ('httpRoute', 'enabled'), False, 'enableS3 requires'),
            ('missing-parentName', ('httpRoute', 'parentName'), None, 'httpRoute.parentName'),
        ]
        for name, path, value, error in cases:
            env = deepcopy(ENVIRONMENT)
            target = env['data'][path[0]]
            if value is None:
                del target[path[1]]
            else:
                target[path[1]] = value
            render(env, error=error)
            print(f'PASS rejected configuration: {name}', flush=True)

        env = deepcopy(ENVIRONMENT)
        env['data']['ingress'].update({'enabled': True, 'class': 'nginx'})
        env['data']['httpRoute']['enabled'] = False
        env['data']['httpRoute']['enableS3'] = False
        render(env, error='ingress.secret')
        print('PASS rejected configuration: missing-ingress-secret', flush=True)

        env = deepcopy(ENVIRONMENT)
        env['data']['storage'] = {'forcePathStyle': False}
        output = render(env)
        assert 'AWS_S3_FORCE_PATH_STYLE: "false"' in resource(output, 's-joe-datalab')
        deployment = resource(output, 'data-s3-deployment-s-joe')
        assert re.search(r'name: RCLONE_CONFIG_UPSTREAM_FORCE_PATH_STYLE\s+value: "false"', deployment)
        print('PASS storage.forcePathStyle: false', flush=True)

        source = Path('examples/base/002-lab.yaml').read_text()
        env = deepcopy(ENVIRONMENT)
        env['metadata']['name'] = 'datalab'
        refs = {'parentName': 'default', 'parentNamespace': 'contour', 'sectionName': 'postgres-passthrough'}
        env['data']['database'] = {'tlsRoute': refs}
        stores = {
            'documentStore': 'mongodb-community-s-jeff-prod',
            'cacheStore': 'redis-cache-s-jeff-prod',
        }
        for setting in stores:
            env['data'][setting] = {'storageClassName': f'test-{setting}'}
        current = render(env, source, observed='tests/observed/002-lab.yaml')
        assert 'kind: TLSRoute' in current
        route = resource(current, 'db-tlsroute-s-jeff-pg0')
        assert 'postgres-passthrough' in route and 'namespace: contour' in route
        print('PASS database.tlsRoute listener references', flush=True)
        for setting, name in stores.items():
            assert f'storageClassName: test-{setting}' in resource(current, name)
        print('PASS managed-store StorageClasses from EnvironmentConfig', flush=True)

        observed = list(yaml.safe_load_all(Path('tests/observed/002-lab.yaml').read_text()))
        for item in observed:
            if item['metadata']['name'] == 'workshopenvironment-s-jeff':
                item['status']['atProvider']['manifest']['status']['educates']['namespace'] = 'test-runtime'
        observed_path = work / 'observed.yaml'
        observed_path.write_text(yaml.safe_dump_all(observed))
        output = render(env, source, observed=str(observed_path))
        observer = yaml.safe_load(resource(output, 'observe-database-secret-s-jeff-pg0'))
        cluster = yaml.safe_load(resource(output, 'db-postgrescluster-s-jeff-pg0'))
        for item in (observer, cluster):
            assert item['spec']['forProvider']['manifest']['metadata']['namespace'] == 'test-runtime'
        print('PASS PostgreSQL Secret observer uses the runtime namespace', flush=True)

        env = deepcopy(ENVIRONMENT)
        env['metadata']['name'] = 'datalab-custom'
        env['data']['defaults'] = {
            'data': {'enabled': True, 'readOnlyMount': True},
            'quota': {'memory': '7Gi', 'storage': '9Gi', 'budget': 'large'},
            'overallQuota': {'storage': '50Gi'},
            'security': {'policy': 'restricted', 'externalEgress': False, 'kubernetesAccess': False, 'kubernetesRole': 'view'},
            'registry': {'enabled': True, 'storage': '3Gi'},
            'persistence': {'storageClassName': 'sbs-default-retain'},
            'files': [{'git': {'url': 'https://github.com/versioneer-tech/datalab-example', 'ref': 'origin/main'}}],
        }
        env['data']['storageClasses'] = {'allowed': ['sbs-default', 'sbs-default-retain']}
        env['data']['network'] = {'externalEgressCIDRs': ['0.0.0.0/0']}
        source = {
            'apiVersion': 'pkg.internal/v1beta2',
            'kind': 'Datalab',
            'metadata': {
                'name': 's-joe',
                'annotations': {'datalabs.pkg.internal/environment': 'datalab-custom'},
            },
            'spec': {
                'users': ['joe'],
                'sessions': [{'name': 'default'}],
                'vcluster': False,
                'data': {'enabled': False, 'readOnlyMount': False},
                'security': {'policy': 'privileged', 'externalEgress': True, 'kubernetesAccess': True, 'kubernetesRole': 'admin'},
                'quota': {'memory': '1Gi', 'storage': '1Gi', 'budget': 'small'},
                'overallQuota': {'storage': '1Gi'},
                'registry': {'enabled': False},
                'persistence': {'storageClassName': 'sbs-default'},
                'files': [],
            },
        }
        # Removed XR fields must not override the operator's environment settings.
        output = render(env, json.dumps(source))
        workshop = resource(output, 'workshop-s-joe')
        deployment = resource(output, 'data-deployment-s-joe')
        assert deployment and '--perm.create=true' not in deployment
        assert 'memory: 7Gi' in workshop and 'budget: large' in workshop
        assert 'role: view' in workshop and 'policy: restricted' in workshop
        assert 'docker:' not in workshop and 'allow-external-egress' not in workshop
        assert re.search(r'token:\s+enabled: false', workshop)
        assert re.search(r'registry:\s+enabled: true\s+storage: 3Gi', workshop)
        assert 'https://github.com/versioneer-tech/datalab-example' in workshop
        assert re.search(r'vcluster:\s+enabled: true', workshop)
        assert 'allow-vcluster-egress' in workshop
        assert 'name: KUBECONFIG' in resource(output, 'workshopsession-s-joe-default')
        pvc = resource(output, 'persistentvolumeclaim-s-joe-default-persistent')
        assert 'storage: 9Gi' in pvc and 'storageClassName: sbs-default-retain' in pvc
        quota = resource(output, 'resourcequota-s-joe-overall-storage')
        assert 'requests.storage: 50Gi' in quota
        print('PASS environment-only security, session, and aggregate quota settings', flush=True)

        env['data']['defaults']['vcluster'] = {'enabled': False}
        source['spec']['vcluster'] = {'enabled': True}
        disabled = render(env, json.dumps(source))
        workshop = resource(disabled, 'workshop-s-joe')
        assert re.search(r'vcluster:\s+enabled: false', workshop)
        assert 'allow-vcluster-egress' not in workshop
        assert 'name: KUBECONFIG' not in resource(disabled, 'workshopsession-s-joe-default')
        print('PASS environment-only vcluster toggle and default true', flush=True)

        env['data']['defaults']['data']['readOnlyMount'] = False
        source['spec']['data']['readOnlyMount'] = True
        writable = render(env, json.dumps(source))
        assert '--perm.create=true' in resource(writable, 'data-deployment-s-joe')
        env['data']['defaults']['data']['enabled'] = False
        env['data']['defaults']['registry']['enabled'] = False
        source['spec']['registry']['enabled'] = True
        source['spec']['data']['enabled'] = True
        disabled_data = render(env, json.dumps(source))
        assert not resource(disabled_data, 'data-deployment-s-joe')
        assert not resource(disabled_data, 'observe-runtime-storage-secret-s-joe')
        assert not resource(disabled_data, 's-joe-s-joe-audience')
        assert 'name: Data' not in resource(disabled_data, 'workshop-s-joe')
        assert not re.search(r'^\s+registry:', resource(disabled_data, 'workshop-s-joe'), re.MULTILINE)
        print('PASS environment-only Data and registry toggles and read-only permissions', flush=True)


if __name__ == '__main__':
    main()
