#!/usr/bin/env python3

"""Use an access token supplied by the caller."""

import argparse
import base64
from binascii import Error as Base64Error
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--access-token-file', default=os.environ.get('DATALAB_ACCESS_TOKEN_FILE'))
    args = parser.parse_args()
    if not args.access_token_file:
        parser.error('Supply --access-token-file or set DATALAB_ACCESS_TOKEN_FILE.')
    try:
        token = Path(args.access_token_file).read_text().strip()
        if not token:
            raise ValueError('Empty access token')
        payload = token.split('.')[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))
        # The API validates the token. Expiry tells kubectl when to call this helper again.
        expires = datetime.fromtimestamp(claims['exp'], timezone.utc)
    except (OSError, ValueError, Base64Error, IndexError, KeyError, TypeError, OverflowError):
        print('Could not read the access token or its expiry. Check the token file.', file=sys.stderr)
        return 1
    credential = {
        'apiVersion': 'client.authentication.k8s.io/v1', 'kind': 'ExecCredential',
        'status': {'token': token, 'expirationTimestamp': expires.isoformat().replace('+00:00', 'Z')},
    }
    print(json.dumps(credential))
    return 0


if __name__ == '__main__':
    sys.exit(main())
