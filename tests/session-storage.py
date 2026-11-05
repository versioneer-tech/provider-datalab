# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Check zero, unknown, and shared session storage in function responses."""

import json
from pathlib import Path
import subprocess
import sys

import yaml


CHECK = """
import json
import sys

from crossplane.function import response
from crossplane.function.proto.v1 import run_function_pb2 as fnv1
from google.protobuf.json_format import MessageToDict

namespace = {}
exec(compile(json.load(sys.stdin)['input']['script'], 'update-session-status', 'exec'), namespace)

def run(requests, workspace=None):
    req = fnv1.RunFunctionRequest()
    sessions = [{'name': name, 'state': 'stopped' if name == 'saved' else 'started'} for name in requests]
    req.observed.composite.resource.update({
        'metadata': {'name': 's-joe'}, 'spec': {'sessions': sessions},
        'status': {'sessions': [{'name': 'retired', 'pvcSize': '99Gi'}]},
    })
    for name, (volume, size) in requests.items():
        if volume is None:
            continue
        key = f'persistentvolumeclaim-s-joe-{name}-persistent'
        req.desired.resources[key].resource.update({'spec': {'forProvider': {'manifest': {
            'apiVersion': 'v1', 'kind': 'PersistentVolumeClaim',
            'metadata': {'name': volume, 'namespace': 'runtime'},
            'spec': {'resources': {'requests': {'storage': size}}},
        }}}})
    if workspace is not None:
        req.desired.resources['workshop-s-joe'].resource.update({'spec': {'forProvider': {'manifest': {
            'spec': {'session': {'resources': workspace}},
        }}}})
    req.desired.resources['database'].resource.update({'spec': {'forProvider': {'manifest': {
        'kind': 'PersistentVolumeClaim', 'spec': {'resources': {'requests': {'storage': '100Gi'}}},
    }}}})
    rsp = response.to(req)
    namespace['compose'](req, rsp)
    return MessageToDict(rsp.desired.composite.resource)['status']['sessions']

entries = run({'default': ('shared', '10Gi'), 'analysis': ('shared', '10Gi'), 'saved': ('retained', '5Gi')})
assert [e['pvcSize'] for e in entries] == ['10Gi', '0', '5Gi']
assert entries[0]['pvcRef'] == entries[1]['pvcRef']
assert entries[2]['state'] == 'stopped' and entries[2]['pvcSize'] == '5Gi'
assert not any(e['name'] == 'retired' for e in entries)

for text in ('0', '0Gi', '0.0', '-0', '0e3'):
    assert run({'default': ('volume', text)})[0]['pvcSize'] == '0'
assert run({'default': (None, None)}, {})[0]['pvcSize'] == '0'
for text in ('1Gi', '1.5Gi', '500M', '1e3', '1E+3', '500m', '1u', '1n'):
    assert run({'default': ('volume', text)})[0]['pvcSize'] == text
for text in (None, '', 'bad', '-1Gi', 'NaN', 'Infinity', '1GB', '1ki', '1K'):
    assert 'pvcSize' not in run({'default': ('volume', text)})[0]
assert 'pvcSize' not in run({'default': (None, None)})[0]
assert 'pvcSize' not in run({'default': (None, None)}, {'volume': {'name': 'external'}})[0]
"""


if __name__ == "__main__":
    pipeline = yaml.safe_load(Path("composition.yaml").read_text())["spec"]["pipeline"]
    step = next(step for step in pipeline if step["step"] == "update-session-status")
    result = subprocess.run(
        ["docker", "exec", "-i", sys.argv[1], "/venv/fn/bin/python", "-c", CHECK],
        input=json.dumps(step), text=True, capture_output=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    print("PASS shared session volumes count once; stopped storage remains; zero and unknown sizes are distinct")
