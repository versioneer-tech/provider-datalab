#!/usr/bin/env python3
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Test Datalab browser routing and read-only S3 access on one hostname."""

import argparse
import configparser
import json
import os
from pathlib import Path
import ssl
import time
import urllib.error
import urllib.request
from urllib.parse import quote

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tenant', default='verify-s3')
    parser.add_argument('--issuer', default='http://keycloak.keycloak:8080/realms/integration')
    parser.add_argument('--browser-only', action='store_true')
    args = parser.parse_args()
    endpoint = f'https://{args.tenant}.lab.local'
    certificate = '/certs/tls.crt'

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *_args):
            return None

    opener = urllib.request.build_opener(
        NoRedirect(), urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=certificate)))
    for url, expected in ((endpoint + '/', 302), (endpoint.replace('https:', 'http:') + '/', 301)):
        try:
            opener.open(url, timeout=10)
        except urllib.error.HTTPError as exc:
            assert exc.code == expected, (url, exc.code)
            location = exc.headers['Location']
            assert location.startswith(args.issuer + '/') if expected == 302 else location.startswith(endpoint)
            print(f'GET {url} -> {exc.code}; Location: {location.split("?")[0]}', flush=True)
        else:
            raise AssertionError('Expected redirect: ' + url)
    if args.browser_only:
        return

    work = Path('/tmp/datalab-s3')
    work.mkdir(exist_ok=True)
    os.environ['AWS_CONFIG_FILE'] = str(work / 'config')
    os.environ['AWS_SHARED_CREDENTIALS_FILE'] = '/dev/null'
    os.environ['AWS_EC2_METADATA_DISABLED'] = 'true'
    config = Config(signature_version='s3v4', s3={'addressing_style': 'path'}, retries={'max_attempts': 0},
                    connect_timeout=5, read_timeout=15, user_agent='verify-s3-client')
    profile = configparser.RawConfigParser()
    profile['profile datalab'] = {
        'region': 'us-east-1',
        'credential_process': f'python /test/s3-credentials.py --tenant {args.tenant} --issuer {args.issuer}',
    }
    with (work / 'config').open('w') as stream:
        profile.write(stream)
    client = boto3.Session(profile_name='datalab').client('s3', endpoint_url=endpoint, verify=certificate, config=config)

    # Seed the disposable backend. Public S3 access must remain read only.
    storage = boto3.client('s3', endpoint_url='http://default-hl.minio:9000', region_name='us-east-1',
                           aws_access_key_id='minioadmin', aws_secret_access_key='minioadmin', config=config)
    bucket = 'verify-s3-data'
    try:
        storage.create_bucket(Bucket=bucket)
    except ClientError as exc:
        if exc.response['Error']['Code'] not in ('BucketAlreadyOwnedByYou', 'BucketAlreadyExists'):
            raise
    key = 'samples/folder/file with spaces.txt'
    content = b'Datalab S3 range read\n'
    storage.put_object(Bucket=bucket, Key=key, Body=content)
    object_path = '/' + bucket + '/' + quote(key, safe='/')

    def show(method, path, response, body):
        print(f'{method} {endpoint}{path} -> {response["ResponseMetadata"]["HTTPStatusCode"]}; '
              f'{json.dumps(body)}', flush=True)

    # Wait for rclone's cached directory listing to include the new fixture.
    deadline = time.monotonic() + 30
    while True:
        try:
            listed = client.list_objects_v2(Bucket=bucket, Prefix='samples/')
            if key in [item['Key'] for item in listed.get('Contents', [])]:
                break
        except ClientError as exc:
            if exc.response['ResponseMetadata']['HTTPStatusCode'] != 404:
                raise
        if time.monotonic() >= deadline:
            raise AssertionError('The seeded object is not visible through S3.')
        time.sleep(1)
    show('GET', '/' + bucket + '?list-type=2&prefix=samples%2F', listed,
         {'Keys': [item['Key'] for item in listed['Contents']]})
    head = client.head_object(Bucket=bucket, Key=key)
    assert head['ContentLength'] == len(content)
    show('HEAD', object_path, head, {'Content-Length': head['ContentLength']})
    full = client.get_object(Bucket=bucket, Key=key)
    assert full['Body'].read() == content
    show('GET', object_path, full, {'Body': content.decode()})
    ranged = client.get_object(Bucket=bucket, Key=key, Range='bytes=4-10')
    assert ranged['Body'].read() == content[4:11]
    assert ranged['ContentRange'] == f'bytes 4-10/{len(content)}'
    show('GET Range: bytes=4-10', object_path, ranged,
         {'Content-Range': ranged['ContentRange'], 'Body': content[4:11].decode()})

    for method, operation, extra in (('PUT', 'put_object', {'Body': b'replacement'}),
                                      ('DELETE', 'delete_object', {})):
        try:
            getattr(client, operation)(Bucket=bucket, Key=key, **extra)
        except ClientError as exc:
            assert exc.response['ResponseMetadata']['HTTPStatusCode'] == 403
            show(method, object_path, exc.response, {'Result': 'read-only request rejected'})
        else:
            raise AssertionError('Read-only S3 accepted ' + method)
    assert client.get_object(Bucket=bucket, Key=key)['Body'].read() == content
    storage.delete_object(Bucket=bucket, Key=key)
    storage.delete_bucket(Bucket=bucket)
    print('PASS shared hostname, generated client credentials, S3 reads and read-only enforcement', flush=True)


if __name__ == '__main__':
    main()
