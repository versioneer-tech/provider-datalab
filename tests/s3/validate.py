#!/usr/bin/env python3
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Render endpoint configurations and check routing and prerequisite failures."""

import argparse
from copy import deepcopy
import json
import re
from pathlib import Path
import subprocess
import tempfile


ENVIRONMENT = {
    'apiVersion': 'apiextensions.crossplane.io/v1beta1',
    'kind': 'EnvironmentConfig',
    'metadata': {'name': 'datalab-custom'},
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
    parser.add_argument('--functions', default='educates/dependencies/functions.yaml')
    parser.add_argument('--network')
    args = parser.parse_args()
    datalab = Path('examples/base/001-lab.yaml').read_text()
    with tempfile.TemporaryDirectory(prefix='data-routing-') as directory:
        work = Path(directory)

        def render(environment, source=datalab, error=None, observed='educates/tests/observed/001-lab.yaml'):
            (work / 'environment.json').write_text(json.dumps(environment))
            (work / 'datalab.yaml').write_text(source)
            result = subprocess.run([
                'crossplane', 'render', str(work / 'datalab.yaml'), 'educates/composition.yaml',
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
                source = source.replace('spec:\n', 'spec:\n  data:\n    enabled: false\n', 1)
            output = render(env, source)
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
            assert ('included.client.audience: s-joe' in output) == (exposure in ('gateway-s3',))
            assert bool(resource(output, 'data-deployment-s-joe')) == (exposure != 'disabled-data')
            print(f'PASS endpoint configuration: {exposure}', flush=True)

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
        current = render(env, source, observed='educates/tests/observed/002-lab.yaml')
        assert 'kind: TLSRoute' in current
        route = resource(current, 'db-tlsroute-s-jeff-pg0')
        assert 'postgres-passthrough' in route and 'namespace: contour' in route
        print('PASS database.tlsRoute listener references', flush=True)


if __name__ == '__main__':
    main()
