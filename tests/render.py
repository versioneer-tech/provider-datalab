# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Shared composition rendering and snapshot format."""

import argparse
from copy import deepcopy
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile

import yaml

ROOT = Path(__file__).resolve().parents[1]
DUMPER = runpy.run_path(str(ROOT / "scripts/build-composition.py"))["Dumper"]


def arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--functions", default="dependencies/functions.yaml")
    parser.add_argument("--network")
    return parser.parse_args()


def load(path):
    return yaml.safe_load(Path(path).read_text())


def environment():
    return {
        "apiVersion": "apiextensions.crossplane.io/v1beta1",
        "kind": "EnvironmentConfig",
        "metadata": {"name": "datalab-educates",
                     "labels": {"datalabs.pkg.internal/name": "datalab-educates"}},
        "data": {
            "iam": {"realm": "acme", "issuerURL": "https://identity.acme.com/realms/acme",
                    "internalURL": "http://keycloak.keycloak:8080/realms/acme"},
            "storage": {"secretNamespace": "datalab"},
            "ingress": {"enabled": False, "domain": "lab.acme.com"},
            "httpRoute": {"enabled": True, "enableS3": True, "parentName": "default",
                          "parentNamespace": "contour", "sectionName": "workspaces-https",
                          "httpSectionName": "workspaces-http"},
        },
    }


def requirements(environment, observed):
    def documents(value):
        if isinstance(value, (str, Path)):
            return list(yaml.safe_load_all(Path(value).read_text()))
        return value if isinstance(value, list) else [value]

    required = deepcopy(documents(environment))
    identities = {(item.get("metadata", {}).get("namespace"), item.get("metadata", {}).get("name"))
                  for item in required if item.get("kind") == "Secret"}
    # Supply native Secrets separately from the synthetic Object observer state.
    for item in documents(observed):
        manifest = item.get("status", {}).get("atProvider", {}).get("manifest", {})
        data = manifest.get("data") or manifest.get("stringData")
        metadata = manifest.get("metadata") or {}
        identity = (metadata.get("namespace"), metadata.get("name"))
        if (manifest.get("kind") == "Secret" and data and data != {"redacted": None}
                and all(identity) and identity not in identities):
            required.append(deepcopy(manifest))
            identities.add(identity)
    return required


def render(args, environment, source="examples/base/001-lab.yaml",
           observed="tests/observed/001-lab.yaml", error=None, include_composite=False):
    environment = requirements(environment, observed)
    with tempfile.TemporaryDirectory(prefix="test-render-") as directory:
        work = Path(directory)
        paths = []
        for name, value in (("source", source), ("environment", environment), ("observed", observed)):
            if isinstance(value, (str, Path)):
                paths.append(str(value))
            else:
                path = work / f"{name}.yaml"
                path.write_text(yaml.safe_dump_all(value if isinstance(value, list) else [value]))
                paths.append(str(path))
        result = subprocess.run(
            ["crossplane", "render", paths[0], "composition.yaml", args.functions,
             "--required-resources", paths[1], "--observed-resources", paths[2], "-x"]
            + (["--crossplane-docker-network", args.network] if args.network else []),
            capture_output=True, text=True, timeout=120,
        )
    if error:
        assert result.returncode != 0, "Invalid configuration was accepted"
        assert error in result.stderr, result.stderr
        return {}
    assert result.returncode == 0, result.stderr
    resources = {}
    for item in yaml.safe_load_all(result.stdout):
        if item["kind"] == "Datalab":
            if include_composite:
                resources["composite"] = item
            continue
        name = item["metadata"]["annotations"]["crossplane.io/composition-resource-name"]
        assert name not in resources, f"Duplicate resource: {name}"
        resources[name] = item
    return resources


def manifest(resources, name):
    return resources[name]["spec"]["forProvider"]["manifest"]


def snapshot(path):
    resources = list(yaml.safe_load_all(Path(path).read_text()))
    for item in resources:
        if item["kind"] == "Datalab":
            # Resource references repeat the composed resources below.
            crossplane = item.get("spec", {}).get("crossplane", {})
            crossplane.pop("resourceRefs", None)
            if not crossplane:
                item.get("spec", {}).pop("crossplane", None)
            item.get("status", {}).pop("conditions", None)
            if not item.get("status"):
                item.pop("status", None)
        else:
            metadata = item["metadata"]
            metadata.pop("ownerReferences", None)
            annotations = metadata.get("annotations", {})
            if annotations.get("crossplane.io/composition-resource-name") == metadata["name"]:
                annotations.pop("crossplane.io/composition-resource-name")
            metadata.get("labels", {}).pop("crossplane.io/composite", None)
            for field in ("annotations", "labels"):
                if not metadata.get(field):
                    metadata.pop(field, None)
    return yaml.dump_all(resources, Dumper=DUMPER, sort_keys=False, width=110, explicit_start=True)


if __name__ == "__main__":
    if sys.argv[1] == "requirements":
        observed = sys.argv[3] if len(sys.argv) > 3 and sys.argv[3] else []
        sys.stdout.write(yaml.safe_dump_all(requirements(sys.argv[2], observed)))
    else:
        sys.stdout.write(snapshot(sys.argv[1]))
