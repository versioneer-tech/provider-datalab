# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Check login role scopes, refresh, and exchange in a disposable Keycloak server."""

import base64
import json
from pathlib import Path
import subprocess
import tempfile
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import uuid

import yaml


def verify_keycloak_policy(resources, image=None):
    def params(kind):
        return [item['spec']['forProvider'] for item in resources.values() if item.get('kind') == kind]

    client = params('Client')[0]
    client_id = client['clientId']
    scopes = {item['metadata']['name']: item['spec']['forProvider']['name']
              for item in resources.values() if item.get('kind') == 'ClientScope'}
    role_names = {item['metadata']['name']: item['spec']['forProvider']['name']
                  for item in resources.values() if item.get('kind') == 'Role'}
    member_grants = next(item for item in params('Roles') if item['groupIdRef']['name'] == client_id)
    member_roles = [role_names[item['name']] for item in member_grants['roleIdsRefs']]
    login_client_id = 'test-workspace-api'
    other_client_id = 'test-other-workspace'
    root_mappers, scope_mappers = [], {name: [] for name in scopes.values()}
    for item in params('ProtocolMapper'):
        mapper = {key: item[key] for key in ['name', 'protocol', 'protocolMapper', 'config']}
        if 'clientScopeIdRef' in item:
            scope_mappers[scopes[item['clientScopeIdRef']['name']]].append(mapper)
        else:
            root_mappers.append(mapper)
    mappings = []
    for item in params('RoleMapper'):
        if 'clientScopeIdRef' in item:
            mappings.append({'clientScope': scopes[item['clientScopeIdRef']['name']],
                             'roles': [role_names[item['roleIdRef']['name']]]})
    profile = params('ClientPolicyProfile')[0]
    policy = params('ClientPolicyProfilePolicy')[0]

    def configuration(value):
        result = {}
        for key, field in value.items():
            try:
                result[key] = json.loads(field)
            except (ValueError, TypeError):
                result[key] = field
        return result

    policies = {'policies': [{'name': policy['name'], 'enabled': False,
        'conditions': [{'condition': item['name'], 'configuration': configuration(item.get('configuration', {}))}
                       for item in policy['condition']], 'profiles': [profile['name']]}]}
    realm = {
        'realm': 'test-refresh', 'enabled': True,
        'roles': {'client': {client_id: [{'name': name} for name in role_names.values()],
                             other_client_id: [{'name': 'ws_access'}]}},
        'groups': [{'name': client_id, 'clientRoles': {client_id: member_roles}},
                   {'name': other_client_id, 'clientRoles': {other_client_id: ['ws_access']}}],
        'users': [{'username': 'test-user', 'enabled': True, 'emailVerified': True,
                   'firstName': 'Test', 'lastName': 'User', 'email': 'test@example.test',
                   'realmRoles': ['offline_access'], 'clientRoles': {client_id: list(role_names.values())},
                   'credentials': [{'type': 'password', 'value': 'test-password', 'temporary': False}]},
                  {'username': 'test-member', 'enabled': True, 'emailVerified': True,
                   'firstName': 'Test', 'lastName': 'Member', 'email': 'member@example.test',
                   'groups': ['/' + client_id, '/' + other_client_id],
                   'credentials': [{'type': 'password', 'value': 'test-password', 'temporary': False}]}],
        'clients': [{'clientId': client_id, 'secret': 'test-secret', 'protocol': 'openid-connect',
                     'publicClient': False, 'directAccessGrantsEnabled': True, 'standardFlowEnabled': True,
                     'fullScopeAllowed': False, 'defaultClientScopes': ['basic', 'profile', 'email'],
                     'optionalClientScopes': params('ClientOptionalScopes')[0]['optionalScopes'],
                     'attributes': {'standard.token.exchange.enabled': 'true',
                         'client.offline.session.idle.timeout': client['clientOfflineSessionIdleTimeout'],
                         'client.offline.session.max.lifespan': client['clientOfflineSessionMaxLifespan']},
                     'protocolMappers': root_mappers},
                    {'id': login_client_id, 'clientId': login_client_id, 'protocol': 'openid-connect',
                     'publicClient': True, 'directAccessGrantsEnabled': True,
                     'fullScopeAllowed': False, 'defaultClientScopes': ['basic'],
                     'protocolMappers': [{'name': 'client roles', 'protocol': 'openid-connect',
                         'protocolMapper': 'oidc-usermodel-client-role-mapper',
                         'config': {'claim.name': 'resource_access.${client_id}.roles',
                                    'access.token.claim': 'true', 'multivalued': 'true',
                                    'jsonType.label': 'String'}}]},
                    {'clientId': other_client_id, 'protocol': 'openid-connect', 'publicClient': True,
                     'fullScopeAllowed': False}],
        'clientScopes': [{'name': 'basic', 'protocol': 'openid-connect', 'protocolMappers': [
                            {'name': 'sub', 'protocol': 'openid-connect', 'protocolMapper': 'oidc-sub-mapper',
                             'config': {'access.token.claim': 'true', 'introspection.token.claim': 'true'}}]},
                         *[{'name': name, 'protocol': 'openid-connect',
                          'attributes': {'include.in.token.scope': 'true'}, 'protocolMappers': mappers}
                         for name, mappers in scope_mappers.items()]],
        'clientScopeMappings': {client_id: mappings},
        'clientProfiles': {'profiles': [{'name': profile['name'], 'executors': [
            {'executor': item['name'], 'configuration': configuration(item.get('configuration', {}))}
            for item in profile['executor']]}]},
        'clientPolicies': policies,
    }
    if image is None:
        manifest = yaml.safe_load_all(Path('tests/integration/manifests/s3/keycloak.yaml').read_text())
        image = next(item['spec']['template']['spec']['containers'][0]['image']
                     for item in manifest if item and item.get('kind') == 'Deployment')
    name = 'test-keycloak-' + uuid.uuid4().hex[:12]

    def docker(*arguments):
        result = subprocess.run(['docker', *arguments], capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError('Keycloak test Docker command failed: ' + arguments[0])
        return result.stdout.strip()

    def call(path, values=None, token=None, body=None, method=None):
        data = urlencode(values).encode() if values is not None else None
        headers = {'Authorization': 'Bearer ' + token} if token else {}
        if body is not None:
            data = json.dumps(body).encode(); headers['Content-Type'] = 'application/json'
        if method is None and body is not None:
            method = 'PUT'
        try:
            with urlopen(Request(origin + path, data=data, headers=headers, method=method), timeout=10) as response:
                raw = response.read()
                return response.status, json.loads(raw) if raw else {}
        except HTTPError as error:
            return error.code, json.load(error)

    def claims(token):
        value = token.split('.')[1]
        return json.loads(base64.urlsafe_b64decode(value + '=' * (-len(value) % 4)))

    with tempfile.TemporaryDirectory(prefix='test-keycloak-') as directory:
        work = Path(directory)
        work.chmod(0o755)
        source = work / 'realm.json'
        source.write_text(json.dumps(realm)); source.chmod(0o644)
        try:
            # This disposable realm needs no disk database or persistent state.
            docker('run', '--detach', '--name', name, '-p', '127.0.0.1::8080',
                   '-e', 'KC_BOOTSTRAP_ADMIN_USERNAME=test-admin', '-e', 'KC_BOOTSTRAP_ADMIN_PASSWORD=test-admin-password',
                   '-v', str(work) + ':/opt/keycloak/data/import:ro', image, 'start-dev', '--db=dev-mem', '--import-realm')
            port = docker('port', name, '8080/tcp').rsplit(':', 1)[1]
            origin = 'http://127.0.0.1:' + port
            endpoint = '/realms/test-refresh/protocol/openid-connect/token'
            # A cold dev image builds the server and database before realm import.
            deadline = time.monotonic() + 600
            while True:
                try:
                    status, _ = call('/realms/test-refresh/.well-known/openid-configuration')
                    if status == 200:
                        break
                except OSError:
                    pass
                if time.monotonic() >= deadline:
                    logs = subprocess.run(['docker', 'logs', '--tail', '40', name],
                                          capture_output=True, text=True)
                    raise RuntimeError('The local Keycloak test server did not start:\n'
                                       + logs.stdout + logs.stderr)
                time.sleep(1)
            status, admin = call('/realms/master/protocol/openid-connect/token', {
                'grant_type': 'password', 'client_id': 'admin-cli', 'username': 'test-admin', 'password': 'test-admin-password'})
            assert status == 200, 'Local Keycloak test administration failed'
            member_login = {'grant_type': 'password', 'client_id': login_client_id,
                            'username': 'test-member', 'password': 'test-password', 'scope': 'openid'}
            status, unscoped = call(endpoint, member_login)
            assert status == 200, 'The separate client login failed'
            assert not claims(unscoped['access_token']).get('resource_access'), 'Group membership bypassed role scopes'
            admin_path = '/admin/realms/test-refresh/clients'
            status, workspace_clients = call(admin_path + '?' + urlencode({'clientId': client_id}),
                                            token=admin['access_token'])
            assert status == 200 and len(workspace_clients) == 1, 'The workspace client was not found'
            workspace_path = admin_path + '/' + workspace_clients[0]['id']
            permitted_roles = []
            for role in ('ws_access', 'ws_api', 'ws_admin'):
                status, representation = call(workspace_path + '/roles/' + role, token=admin['access_token'])
                assert status == 200, 'The workspace role was not found'
                permitted_roles.append(representation)
            mapping_path = admin_path + '/' + login_client_id + '/scope-mappings/clients/' + workspace_clients[0]['id']
            status, _ = call(mapping_path, token=admin['access_token'], body=permitted_roles, method='POST')
            assert status == 204, 'The separate client role scope mappings were not added'
            status, scoped = call(endpoint, member_login)
            assert status == 200, 'Login after role scope mapping failed'
            access = claims(scoped['access_token']).get('resource_access', {})
            assert {name: set(value['roles']) for name, value in access.items()} == {
                client_id: {'ws_access', 'ws_api'}
            }, 'Role scopes lost member grants or included administrator, profile, or unrelated workspace roles'
            status, login_client = call(admin_path + '/' + login_client_id, token=admin['access_token'])
            assert status == 200 and login_client['fullScopeAllowed'] is False
            print('PASS separate login needs explicit role scopes and includes only held workspace roles', flush=True)
            credentials = {'client_id': client_id, 'client_secret': 'test-secret'}
            status, human = call(endpoint, {**credentials, 'grant_type': 'password', 'username': 'test-user',
                'password': 'test-password', 'scope': 'openid offline_access ' + client_id + ':interactive'})
            assert status == 200, 'Local test user token issuance failed'
            original = claims(human['access_token'])
            original_roles = set(original['resource_access'][client_id]['roles'])
            assert 'vcluster_vc0_cluster-admin' in original_roles
            assert claims(human['refresh_token'])['typ'] == 'Offline', 'The CLI login did not receive offline access'
            policies['policies'][0]['enabled'] = True
            status, _ = call('/admin/realms/test-refresh/client-policies/policies', token=admin['access_token'], body=policies)
            assert status == 204, 'Local test policy activation failed'
            status, refreshed = call(endpoint, {**credentials, 'grant_type': 'refresh_token', 'refresh_token': human['refresh_token']})
            assert status == 200, 'The exchange policy rejected human refresh'
            renewed = claims(refreshed['access_token'])
            assert renewed['sub'] == original['sub']
            assert set(renewed['resource_access'][client_id]['roles']) == original_roles
            print('PASS real Keycloak offline refresh preserves the human subject and administrator roles', flush=True)
            exchange = {**credentials, 'grant_type': 'urn:ietf:params:oauth:grant-type:token-exchange',
                'subject_token': refreshed['access_token'], 'subject_token_type': 'urn:ietf:params:oauth:token-type:access_token',
                'requested_token_type': 'urn:ietf:params:oauth:token-type:access_token', 'audience': client_id}
            scope = client_id + ':vclusters_vc0_namespace-demo'
            status, delegated = call(endpoint, {**exchange, 'scope': scope})
            assert status == 200, 'The namespace token exchange failed'
            delegated_claims = claims(delegated['access_token'])
            assert delegated_claims['sub'] == original['sub']
            assert set(delegated_claims['resource_access'][client_id]['roles']) == {'ws_api', 'vcluster_vc0_namespace-demo'}
            assert not delegated.get('refresh_token')
            for selected in [client_id + ':interactive', client_id + ':interactive ' + scope]:
                status, rejected = call(endpoint, {**exchange, 'scope': selected})
                assert status == 400 and rejected.get('error') == 'invalid_request', 'Interactive exchange was not rejected'
            print('PASS real Keycloak exchange keeps only the selected role and rejects interactive and mixed scopes', flush=True)
        finally:
            subprocess.run(['docker', 'rm', '-f', name], capture_output=True)
