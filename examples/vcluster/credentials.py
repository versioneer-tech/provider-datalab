#!/usr/bin/env python3
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Use a caller's access token or request one with the Datalab OAuth client."""

import argparse
import base64
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import ssl
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--issuer', required=True)
    parser.add_argument('--client-id', required=True)
    source = parser.add_mutually_exclusive_group()
    source.add_argument('--access-token-file', default=os.environ.get('DATALAB_ACCESS_TOKEN_FILE'))
    source.add_argument('--client-secret-file', default=os.environ.get('DATALAB_CLIENT_SECRET_FILE'))
    source.add_argument('--client-secret-env')
    parser.add_argument('--issuer-ca')
    parser.add_argument('--issuer-ca-data')
    args = parser.parse_args()
    if sum(bool(value) for value in (args.access_token_file, args.client_secret_file, args.client_secret_env)) != 1:
        parser.error('Supply one access token file or client secret source. Set DATALAB_ACCESS_TOKEN_FILE or DATALAB_CLIENT_SECRET_FILE.')
    if not args.issuer.startswith('https://'):
        parser.error('--issuer must use HTTPS')
    try:
        if args.access_token_file:
            status = {'token': Path(args.access_token_file).read_text().strip()}
        else:
            secret = (Path(args.client_secret_file).read_text().strip() if args.client_secret_file
                      else os.environ[args.client_secret_env])
            if not secret:
                raise ValueError('Empty client secret')
            ca_data = base64.b64decode(args.issuer_ca_data).decode() if args.issuer_ca_data else None
            context = ssl.create_default_context(cafile=args.issuer_ca, cadata=ca_data)
            request = Request(args.issuer.rstrip('/') + '/protocol/openid-connect/token',
                              data=urlencode({'grant_type': 'client_credentials', 'client_id': args.client_id,
                                              'client_secret': secret}).encode())
            with urlopen(request, context=context, timeout=30) as result:
                token = json.load(result)
            expires = datetime.now(timezone.utc) + timedelta(seconds=int(token['expires_in']) - 10)
            status = {'token': token['access_token'], 'expirationTimestamp': expires.isoformat().replace('+00:00', 'Z')}
        if not status['token']:
            raise ValueError('Empty access token')
        credential = {
            'apiVersion': 'client.authentication.k8s.io/v1', 'kind': 'ExecCredential',
            'status': status,
        }
    except (OSError, HTTPError, URLError, ValueError, KeyError):
        print('Could not obtain a Datalab API token. Check the token file or issuer and client credential.', file=sys.stderr)
        return 1
    print(json.dumps(credential))
    return 0


if __name__ == '__main__':
    sys.exit(main())
