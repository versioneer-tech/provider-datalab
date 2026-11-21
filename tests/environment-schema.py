# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Validate Datalab input with the Kubernetes schema validator."""

import json
from pathlib import Path
import subprocess
import tempfile

import yaml


def main():
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
        (True, {"analysis": {"vcluster": "vc0", "backup": True}}, None),
        (True, {"recovered-analysis": {"vcluster": "vc0", "restoreFrom": "saved-analysis"}}, None),
        (False, {"analysis": {"vcluster": "missing"}}, "spec"),
        (False, {"Uppercase": {"vcluster": "vc0"}}, "spec.volumes"),
        (False, {"analysis": {"vcluster": "vc0", "backup": "yes"}}, "spec.volumes.analysis.backup"),
        (False, {"analysis": {"vcluster": "vc0", "namespace": "kube-system"}}, "spec.volumes[analysis].namespace"),
        (False, {"analysis": {"vcluster": "vc0", "restoreFrom": "invalid/source"}}, "spec.volumes.analysis.restoreFrom"),
    ]
    for index, (accepted, volumes, field) in enumerate(volume_cases):
        name = "test-volumes-" + str(index)
        expected[name] = accepted, field
        resources.append({"apiVersion": "versioneer.at/v1", "kind": "Datalab",
                          "metadata": {"name": name, "namespace": "workspace"},
                          "spec": {"users": [], "vclusters": {"vc0": {}}, "volumes": volumes}})
    expected.update({item["metadata"]["name"]: (True, None) for item in resources if item["metadata"]["name"] not in expected})
    with tempfile.TemporaryDirectory(prefix="test-datalab-schema-") as directory:
        path = Path(directory) / "resources.yaml"
        path.write_text(yaml.safe_dump_all(resources))
        result = subprocess.run(
            ["crossplane", "resource", "validate", "xrd.yaml", str(path),
             "--crossplane-image=xpkg.crossplane.io/crossplane/crossplane:v2.4.3",
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
    print("PASS environment names, volume contracts, and all base examples", flush=True)


if __name__ == "__main__":
    main()
