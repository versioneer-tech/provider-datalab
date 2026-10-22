#!/usr/bin/env python3
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Get AWS process credentials with CLIENT_SECRET and the client credentials grant."""

import argparse
import datetime
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


def credentials(tenant, issuer, secret):
    started = time.time()
    request = urllib.request.Request(
        issuer.rstrip("/") + "/protocol/openid-connect/token",
        data=urllib.parse.urlencode({
            "grant_type": "client_credentials",
            "client_id": tenant,
            "client_secret": secret,
            "scope": "openid",
        }).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        token = json.load(response)
    expiry = started + float(token["expires_in"])
    if not token["access_token"] or not math.isfinite(expiry) or expiry <= time.time():
        raise ValueError("Invalid token response")
    return {
        "Version": 1,
        "AccessKeyId": tenant,
        "SecretAccessKey": tenant,
        "SessionToken": token["access_token"],
        "Expiration": datetime.datetime.fromtimestamp(expiry, datetime.timezone.utc).isoformat(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--issuer", required=True)
    args = parser.parse_args()
    secret = os.environ.get("CLIENT_SECRET")
    if not secret:
        parser.error("Set CLIENT_SECRET to the OAuth client secret.")
    try:
        output = credentials(args.tenant, args.issuer, secret)
    except urllib.error.HTTPError as error:
        print(f"IAM token request failed (HTTP {error.code}). Check CLIENT_SECRET and client settings.", file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError, TypeError, OverflowError):
        print("Cannot obtain S3 credentials. Check the issuer URL and IAM token response.", file=sys.stderr)
        return 1
    print(json.dumps(output))
    return 0


if __name__ == "__main__":
    sys.exit(main())
