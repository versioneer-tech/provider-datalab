#!/usr/bin/env python3
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Get a short-lived Kubernetes credential with the Datalab OAuth client."""

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
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--client-secret-file')
    source.add_argument('--client-secret-env')
    parser.add_argument('--issuer-ca')
    parser.add_argument('--issuer-ca-data')
    args = parser.parse_args()
    if not args.issuer.startswith('https://'):
        parser.error('--issuer must use HTTPS')
    try:
        secret = (Path(args.client_secret_file).read_text().strip() if args.client_secret_file
                  else os.environ[args.client_secret_env])
        ca_data = base64.b64decode(args.issuer_ca_data).decode() if args.issuer_ca_data else None
        context = ssl.create_default_context(cafile=args.issuer_ca, cadata=ca_data)
        request = Request(args.issuer.rstrip('/') + '/protocol/openid-connect/token',
                          data=urlencode({'grant_type': 'client_credentials', 'client_id': args.client_id,
                                          'client_secret': secret}).encode())
        with urlopen(request, context=context, timeout=30) as result:
            token = json.load(result)
        expires = datetime.now(timezone.utc) + timedelta(seconds=int(token['expires_in']) - 10)
        credential = {
            'apiVersion': 'client.authentication.k8s.io/v1', 'kind': 'ExecCredential',
            'status': {'token': token['access_token'], 'expirationTimestamp': expires.isoformat().replace('+00:00', 'Z')},
        }
    except (OSError, HTTPError, URLError, ValueError, KeyError):
        print('Could not obtain a Datalab API token. Check the issuer and client credential.', file=sys.stderr)
        return 1
    print(json.dumps(credential))
    return 0


if __name__ == '__main__':
    sys.exit(main())
