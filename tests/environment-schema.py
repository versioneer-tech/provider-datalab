# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Validate Datalab input with the Kubernetes schema validator."""

import json
from pathlib import Path
import runpy
import subprocess
import tempfile

import yaml


def main():
    image = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/components.py"))["image_pin"](
        "xpkg.crossplane.io/crossplane/crossplane")
    xrd = yaml.safe_load(Path("xrd.yaml").read_text())
    valid = ["a", "0", "team-config", "team.config", "a" * 63]
    invalid = ["", "a" * 64, "Uppercase", "under_score", "-leading", "trailing-",
               ".leading", "trailing.", "two..dots", "a.-b", "a-.b", "space name", 1, None]
    resources, expected = [], {}
    version = next(version for version in xrd["spec"]["versions"] if version["name"] == "v1")
    spec = version["schema"]["openAPIV3Schema"]["properties"]["spec"]
    assert "default" not in spec["properties"]["environmentName"]
    assert "environmentName" not in spec.get("required", [])
    cases = [(True, {})] + [(True, {"environmentName": value}) for value in valid]
    cases += [(False, {"environmentName": value}) for value in invalid]
    for index, (accepted, fields) in enumerate(cases):
        name = f"test-v1-{index}"
        expected[name] = accepted, "spec.environmentName"
        resources.append({
            "apiVersion": "versioneer.at/v1", "kind": "Datalab",
            "metadata": {"name": name, "namespace": "workspace"},
            "spec": {"users": [], **fields},
        })
    resources.extend(yaml.safe_load(path.read_text()) for path in sorted(Path("examples/base").glob("00*-lab.yaml")))
    volume_cases = [
        (True, {"recovered-analysis": {"restoreFrom": "saved-analysis"}}, None),
        (True, {"analysis": {}}, None),
        (False, {"Uppercase": {}}, "spec.volumes"),
        (False, {"analysis": {"storage": "invalid"}}, "spec.volumes.analysis.storage"),
        (False, {"analysis": {"restoreFrom": "invalid/source"}}, "spec.volumes.analysis.restoreFrom"),
    ]
    for index, (accepted, volumes, field) in enumerate(volume_cases):
        name = "test-volumes-" + str(index)
        expected[name] = accepted, field
        resources.append({"apiVersion": "versioneer.at/v1", "kind": "Datalab",
                          "metadata": {"name": name, "namespace": "workspace"},
                          "spec": {"users": [], "volumes": volumes}})
    binding_cases = [
        (True, {"name": "analysis", "target": {"namespace": "demo", "name": "analysis"}}, None),
        (False, {"name": "analysis"}, "spec.vclusters.vc0.volumeBindings[0].target"),
        (False, {"name": "analysis", "target": {"namespace": "kube-system", "name": "analysis"}},
         "spec.vclusters[vc0].volumeBindings[0].target.namespace"),
        (False, {"name": "Uppercase", "target": {"namespace": "demo", "name": "analysis"}},
         "spec.vclusters.vc0.volumeBindings[0].name"),
    ]
    for index, (accepted, binding, field) in enumerate(binding_cases):
        name = "test-volume-binding-" + str(index)
        expected[name] = accepted, field
        resources.append({"apiVersion": "versioneer.at/v1", "kind": "Datalab",
                          "metadata": {"name": name, "namespace": "workspace"},
                          "spec": {"users": [], "volumes": {"analysis": {}},
                                   "vclusters": {"vc0": {"volumeBindings": [binding]}}}})
    for service in ("postgres", "valkey", "volume"):
        for index, value in enumerate((True, False, "true", 1, {})):
            name = f"test-{service}-backups-{index}"
            field = "volumes" if service == "volume" else "stores"
            expected[name] = index < 2, f"spec.{field}.analysis.backups"
            config = {"storage": "1Gi", "backups": value}
            if service != "volume":
                config["type"] = service
            resources.append({"apiVersion": "versioneer.at/v1", "kind": "Datalab",
                              "metadata": {"name": name, "namespace": "workspace"},
                              "spec": {"users": [], field: {"analysis": config}}})
    store_cases = [
        (True, {"type": "postgres", "storage": "1Gi"}, None),
        (True, {"type": "valkey", "storage": "1Gi", "names": ["sessions", "jobs"]}, None),
        (False, {"storage": "1Gi"}, "spec.stores.main.type"),
        (False, {"type": "unknown", "storage": "1Gi"}, "spec.stores.main.type"),
        (False, {"type": "postgres", "storage": "1Gi", "names": []}, "spec.stores.main.names"),
        (True, {"type": "valkey", "storage": "1Gi", "backups": True}, None),
    ]
    for index, (accepted, store, field) in enumerate(store_cases):
        name = f"test-store-contract-{index}"
        expected[name] = accepted, field
        resources.append({"apiVersion": "versioneer.at/v1", "kind": "Datalab",
                          "metadata": {"name": name, "namespace": "workspace"},
                          "spec": {"users": [], "stores": {"main": store}}})
    expected.update({item["metadata"]["name"]: (True, None) for item in resources if item["metadata"]["name"] not in expected})
    with tempfile.TemporaryDirectory(prefix="test-datalab-schema-") as directory:
        path = Path(directory) / "resources.yaml"
        # Preserve string quantities such as 1e3 through the Kubernetes YAML parser.
        path.write_text("\n---\n".join(json.dumps(resource) for resource in resources))
        result = subprocess.run(
            ["crossplane", "resource", "validate", "xrd.yaml", str(path),
             "--crossplane-image", image,
             "--cache-dir", "/tmp/provider-datalab-crossplane", "--error-on-missing-schemas", "--output", "json"],
            capture_output=True, text=True, timeout=180,
        )
    assert result.returncode == 1, (result.stdout, result.stderr)
    report = json.loads(result.stdout[result.stdout.index("{"):])
    assert report["summary"]["total"] == len(expected), report
    assert report["summary"]["missingSchemas"] == 0, report
    for item in report["resources"]:
        accepted, field = expected[item["name"]]
        assert item["status"] == ("valid" if accepted else "invalid"), item
        if not accepted:
            assert any(error["field"] == field for error in item["errors"]), item
    print("PASS environment names, volume contracts, backup switches, and all base examples", flush=True)


if __name__ == "__main__":
    main()
