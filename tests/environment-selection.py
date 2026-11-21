# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Check environment selection with the installed function."""

import json
from pathlib import Path
import subprocess
import sys

import yaml

RUNTIME_CHECK = """
import json
import sys

import grpc
from crossplane.function.proto.v1 import run_function_pb2 as fnv1
from crossplane.function.proto.v1 import run_function_pb2_grpc as fnv1_grpc
from google.protobuf.json_format import MessageToDict

data = json.load(sys.stdin)
label = 'datalabs.pkg.internal/name'
with grpc.insecure_channel(data['target'] + ':9443') as channel:
    stub = fnv1_grpc.FunctionRunnerServiceStub(channel)
    layers = ('default', 'composition', 'named', 'datalab')
    for case, explicit_composition, named_environment, available in (
        ('all layers', True, True, layers),
        ('composition fallback', False, True, layers),
        ('named override', True, True, ('default', 'composition', 'named')),
        ('missing named config', True, True, ('default', 'composition')),
        ('omitted environmentName', False, False, ('default', 'composition', 'named')),
        ('named config only', False, True, ('named',)),
        ('Datalab config only', False, False, ('datalab',)),
        ('default only', False, False, ('default',)),
        ('no matching configs', False, True, ()),
    ):
        composition = 'test-composition' if explicit_composition else data['composition']
        names = ['default', composition, 'test-environment', 'test-datalab']
        req = fnv1.RunFunctionRequest()
        spec = {'users': []}
        if explicit_composition:
            spec['crossplane'] = {'compositionRef': {'name': composition}}
        if named_environment:
            spec['environmentName'] = names[2]
        req.observed.composite.resource.update({
            'metadata': {'name': names[3], 'namespace': 'test-space'},
            'spec': spec,
        })
        req.input.update(data['input'])
        configs, expected, annotations = [], {}, {}
        expected_ttl = None
        for index, (layer, name) in enumerate(zip(layers, names)):
            if layer not in available:
                continue
            values = {'domain': f'layer-{index}.example.test',
                      'annotations': {f'layer-{index}': 'retained', 'shared': str(index)}}
            if index == 0:
                values['enabled'] = True
            configs.append({
                'apiVersion': 'apiextensions.crossplane.io/v1beta1',
                'kind': 'EnvironmentConfig',
                'metadata': {'name': name, **({'labels': {label: name}} if index else {})},
                'data': {'ingress': values, 'datalab': {'responseTTL': f'{index + 2}m'}},
            })
            if layer != 'named' or named_environment:
                expected_ttl = f'{index + 2}m'
                expected['domain'] = values['domain']
                annotations.update(values['annotations'])
                if index == 0:
                    expected['enabled'] = True
        if expected:
            expected['annotations'] = annotations
        for name in ('test-unrelated', data['composition'] if explicit_composition else 'test-other'):
            configs.append({'metadata': {'name': name, 'labels': {label: name}},
                            'data': {'ingress': {'domain': 'wrong.example.test'}}})
        # Named configs need the selector label even when their names match.
        configs.extend({'metadata': {'name': name},
                        'data': {'ingress': {'domain': 'unlabeled.example.test'}}}
                       for name in names[1:] if name not in [c['metadata']['name'] for c in configs])
        configs.append({
            'metadata': {'name': 'test-storage-config',
                         'labels': {'storages.pkg.internal/name': composition}},
            'data': {'ingress': {'domain': 'storage.example.test'}},
        })
        rsp = stub.RunFunction(req, timeout=10)
        selectors = dict(rsp.requirements.resources)
        for key, selector in selectors.items():
            selected = req.required_resources[key]
            selected.SetInParent()
            for config in configs:
                metadata = config['metadata']
                matches = (metadata['name'] == selector.match_name
                           if selector.WhichOneof('match') == 'match_name'
                           else all(metadata.get('labels', {}).get(k) == v
                                    for k, v in selector.match_labels.labels.items()))
                if matches:
                    selected.items.add().resource.update(config)
        rsp = stub.RunFunction(req, timeout=10)
        assert not any(r.severity == fnv1.SEVERITY_FATAL for r in rsp.results), rsp.results
        actual = MessageToDict(rsp.context)['apiextensions.crossplane.io/environment']
        assert actual.get('ingress', {}) == expected, (case, actual, expected)
        assert actual.get('datalab', {}).get('responseTTL') == expected_ttl, (case, actual, expected_ttl)
    duplicates = 0
    for key, selector in selectors.items():
        if selector.match_labels.labels.get(label) != data['composition']:
            continue
        for index in (1, 0):
            duplicates += 1
            req.required_resources[key].items.add().resource.update({
                'apiVersion': 'apiextensions.crossplane.io/v1beta1',
                'kind': 'EnvironmentConfig',
                'metadata': {'name': f'test-duplicate-{index}',
                             'labels': {label: data['composition']}},
                'data': {'ingress': {'domain': f'duplicate-{index}.example.test'}},
            })
    assert duplicates == 2, selectors
    rsp = stub.RunFunction(req, timeout=10)
    assert not any(r.severity == fnv1.SEVERITY_FATAL for r in rsp.results), rsp.results
    actual = MessageToDict(rsp.context)['apiextensions.crossplane.io/environment']
    assert actual['ingress']['domain'] == 'duplicate-0.example.test', actual
print('PASS environment config selection and merging')
print('PASS duplicate selector labels select only the first config by name')
"""


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python3 tests/environment-selection.py <Python function container>")
    composition = yaml.safe_load(Path("composition.yaml").read_text())
    step = next(step for step in composition["spec"]["pipeline"] if step["step"] == "environmentConfigs")
    result = subprocess.run(
        ["docker", "exec", "-i", sys.argv[1], "/venv/fn/bin/python", "-c", RUNTIME_CHECK],
        input=json.dumps({
            "input": step["input"], "composition": composition["metadata"]["name"],
            "target": sys.argv[1].removesuffix("-python") + "-function-environment-configs",
        }), text=True, capture_output=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    print(result.stdout, end="", flush=True)


if __name__ == "__main__":
    main()
