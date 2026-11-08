#!/usr/bin/env python3
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Use a caller token or sign in through the Datalab device flow."""

import argparse
import base64
from binascii import Error as Base64Error
from datetime import datetime, timezone
from getpass import getpass, GetPassWarning
import hashlib
import json
import os
from pathlib import Path
import ssl
import sys
import tempfile
import time
import warnings
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class OAuthError(ValueError):
    pass


def token_expiry(token):
    payload = token.split('.')[1]
    claims = json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))
    # The API validates the JWT. This value controls only local token reuse.
    return float(claims['exp'])


def post(issuer, endpoint, values, context):
    request = Request(issuer + '/protocol/openid-connect/' + endpoint,
                      data=urlencode(values).encode())
    try:
        with urlopen(request, context=context, timeout=30) as result:
            return json.load(result)
    except HTTPError as error:
        try:
            code = json.load(error).get('error')
        except (ValueError, AttributeError):
            code = None
        # Do not copy server responses: they can contain credentials.
        raise OAuthError(code or 'token_request_failed') from None


def device_login(issuer, client, scope, context):
    device = post(issuer, 'auth/device', {**client, 'scope': scope}, context)
    print('Open ' + device['verification_uri'] + ' and enter code ' + device['user_code']
          + ' to sign in to ' + client['client_id'] + '.', file=sys.stderr)
    deadline = time.monotonic() + float(device['expires_in'])
    interval = max(1, float(device.get('interval', 5)))
    while time.monotonic() + interval < deadline:
        time.sleep(interval)
        try:
            return post(issuer, 'token', {
                **client, 'grant_type': 'urn:ietf:params:oauth:grant-type:device_code',
                'device_code': device['device_code'],
            }, context)
        except OAuthError as error:
            if str(error) == 'slow_down':
                interval += 5
            elif str(error) != 'authorization_pending':
                raise
    raise OAuthError('expired_token')


def read_cache(path):
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (FileNotFoundError, ValueError):
        return {}


def save_cache(path, value):
    # Replace the file only after the complete token response is stored.
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, prefix='.datalab-token-cache-', delete=False) as output:
        temporary = Path(output.name)
        try:
            os.chmod(temporary, 0o600)
            json.dump(value, output)
            output.close()
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def client_secret(args):
    if args.client_secret_file:
        secret = Path(args.client_secret_file).read_text().strip()
    elif args.client_secret_env:
        secret = os.environ[args.client_secret_env]
    else:
        info = os.environ.get('KUBERNETES_EXEC_INFO')
        interactive = json.loads(info).get('spec', {}).get('interactive', False) if info else True
        if not interactive or not sys.stdin.isatty():
            raise ValueError('Client secret input requires an interactive terminal')
        # Stop instead of echoing the secret if terminal control is unavailable.
        with warnings.catch_warnings():
            warnings.simplefilter('error', GetPassWarning)
            secret = getpass('Client secret for ' + args.client_id + ': ', stream=sys.stderr)
    if not secret:
        raise ValueError('Empty client secret')
    return secret


def login(args):
    scope = ' '.join(sorted(set(['openid', 'offline_access', *(args.scope or [args.client_id + ':interactive'])])))
    key = hashlib.sha256(json.dumps([args.issuer, args.client_id, scope]).encode()).hexdigest()
    directory = Path(args.cache_dir).expanduser()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.is_symlink():
        raise ValueError('The token cache directory must not be a symbolic link')
    os.chmod(directory, 0o700)
    path = directory / (key + '.json')
    cached = {} if args.force_login else read_cache(path)
    try:
        session_expires = float(cached.get('session_expires_at', 0))
    except (ValueError, TypeError):
        session_expires = 0
    if session_expires <= time.time() + 30:
        cached = {}
    try:
        expires = min(float(cached['expires_at']), token_expiry(cached['access_token']))
        if expires > time.time() + 30:
            return cached['access_token'], expires
    except (ValueError, Base64Error, KeyError, IndexError, TypeError):
        pass

    ca_data = base64.b64decode(args.issuer_ca_data).decode() if args.issuer_ca_data else None
    context = ssl.create_default_context(cafile=args.issuer_ca, cadata=ca_data)
    client = {'client_id': args.client_id, 'client_secret': client_secret(args)}
    token = None
    if cached.get('refresh_token'):
        try:
            token = post(args.issuer, 'token', {
                **client, 'grant_type': 'refresh_token', 'refresh_token': cached['refresh_token'],
            }, context)
        except OAuthError as error:
            if str(error) != 'invalid_grant':
                raise
    if token is None:
        cached = {}
        token = device_login(args.issuer, client, scope, context)
        session_expires = time.time() + 30 * 24 * 60 * 60
    expires = min(time.time() + float(token['expires_in']), token_expiry(token['access_token']), session_expires)
    if expires <= time.time() + 30:
        raise ValueError('The issued token has expired')
    save_cache(path, {
        'access_token': token['access_token'], 'expires_at': expires,
        'refresh_token': token.get('refresh_token', cached.get('refresh_token')),
        'session_expires_at': session_expires,
    })
    return token['access_token'], expires


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--issuer')
    parser.add_argument('--client-id')
    parser.add_argument('--token-only', action='store_true', help='Use only a caller token file; never start login.')
    source = parser.add_mutually_exclusive_group()
    source.add_argument('--access-token-file', default=os.environ.get('DATALAB_ACCESS_TOKEN_FILE'))
    source.add_argument('--client-secret-file')
    source.add_argument('--client-secret-env')
    parser.add_argument('--scope', action='append', help='OAuth scope; repeat for more scopes. Default: <client-id>:interactive.')
    parser.add_argument('--cache-dir', default=os.environ.get('DATALAB_TOKEN_CACHE_DIR') or str(
        Path(os.environ.get('XDG_CACHE_HOME') or Path.home() / '.cache') / 'datalab' / 'oidc'))
    parser.add_argument('--force-login', action='store_true', help='Ignore cached tokens and start device login.')
    parser.add_argument('--issuer-ca')
    parser.add_argument('--issuer-ca-data')
    args = parser.parse_args()
    if args.token_only:
        if args.client_secret_file or args.client_secret_env:
            parser.error('--token-only does not accept client credentials.')
        if not args.access_token_file:
            parser.error('Supply --access-token-file or set DATALAB_ACCESS_TOKEN_FILE.')
    else:
        args.client_secret_file = args.client_secret_file or os.environ.get('DATALAB_CLIENT_SECRET_FILE')
    if sum(bool(value) for value in (args.access_token_file, args.client_secret_file, args.client_secret_env)) > 1:
        parser.error('Supply one access token file or client secret source. Set DATALAB_ACCESS_TOKEN_FILE or DATALAB_CLIENT_SECRET_FILE.')
    if not args.access_token_file:
        if not args.issuer or not args.client_id:
            parser.error('Device login requires --issuer and --client-id.')
        if not args.issuer.startswith('https://'):
            parser.error('--issuer must use HTTPS')
        args.issuer = args.issuer.rstrip('/')
    try:
        if args.access_token_file:
            token = Path(args.access_token_file).read_text().strip()
            expires = token_expiry(token)
        else:
            token, expires = login(args)
            expires -= 10
        credential = {
            'apiVersion': 'client.authentication.k8s.io/v1', 'kind': 'ExecCredential',
            'status': {'token': token, 'expirationTimestamp': datetime.fromtimestamp(
                expires, timezone.utc).isoformat().replace('+00:00', 'Z')},
        }
    except OAuthError as error:
        message = {
            'access_denied': 'Device login was denied. Run kubectl again to retry.',
            'expired_token': 'The device code expired. Run kubectl again for a new code.',
            'invalid_client': 'Keycloak rejected the client credentials. Check the client ID and secret.',
            'unauthorized_client': 'Keycloak did not allow this login flow. Check the client settings.',
            'invalid_scope': 'Keycloak rejected the requested login scopes.',
            'invalid_request': 'Keycloak rejected the request. Check client policies and the server refresh-event support.',
        }.get(str(error), 'Keycloak rejected the token request. Check the client and login settings.')
        print(message, file=sys.stderr)
        return 1
    except (OSError, URLError, ValueError, Base64Error, KeyError, IndexError, TypeError, OverflowError,
            EOFError, GetPassWarning):
        print('Could not obtain a Datalab API token. Check the token file, client secret, or device login. '
              'Set DATALAB_ACCESS_TOKEN_FILE or DATALAB_CLIENT_SECRET_FILE, or use an interactive terminal. '
              'For a new login, use --force-login.', file=sys.stderr)
        return 1
    print(json.dumps(credential))
    return 0


if __name__ == '__main__':
    sys.exit(main())
