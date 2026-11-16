# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Validate environment names with the Kubernetes schema validator."""

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
    version = next(version for version in xrd["spec"]["versions"] if version["name"] == "v1beta2")
    spec = version["schema"]["openAPIV3Schema"]["properties"]["spec"]
    assert "default" not in spec["properties"]["environmentName"]
    assert "environmentName" not in spec.get("required", [])
    cases = [(True, {})] + [(True, {"environmentName": value}) for value in valid]
    cases += [(False, {"environmentName": value}) for value in invalid]
    for index, (accepted, fields) in enumerate(cases):
        name = f"test-v1beta2-{index}"
        expected[name] = accepted
        resources.append({
            "apiVersion": "pkg.internal/v1beta2", "kind": "Datalab",
            "metadata": {"name": name, "namespace": "workspace"},
            "spec": {"users": [], **fields},
        })
    resources.extend(yaml.safe_load(path.read_text()) for path in sorted(Path("examples/base").glob("00*-lab.yaml")))
    expected.update({item["metadata"]["name"]: True for item in resources if item["metadata"]["name"] not in expected})
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
        accepted = expected[item["name"]]
        assert item["status"] == ("valid" if accepted else "invalid"), item
        if not accepted:
            assert any(error["field"] == "spec.environmentName" for error in item["errors"]), item
    print("PASS v1beta2 accepts optional DNS names, rejects invalid values, and validates all examples", flush=True)


if __name__ == "__main__":
    main()
