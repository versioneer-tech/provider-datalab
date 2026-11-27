#!/usr/bin/env python3
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Install a saved Configuration through the Kind consumer's offline cache."""

import argparse
import base64
import gzip
import json
from pathlib import Path
import re
import runpy
import subprocess
import tarfile
import time

import yaml

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--kubeconfig", required=True)
    parser.add_argument("--context", required=True)
    args = parser.parse_args()
    if args.context != "kind-provider-datalab-it":
        parser.error("The candidate check requires the dedicated Kind cluster")
    security = runpy.run_path(str(ROOT / "scripts/security.py"))
    security["check_package"](args.package, ROOT)
    digest = subprocess.check_output([str(ROOT / "build/tools/crane"), "digest", "--tarball", str(args.package)], text=True).strip()
    reference = "example.test/datalab@" + digest
    # Crossplane FriendlyID uses the source and the first 12 digest characters.
    key = re.sub(r"[./:]", "-", "example.test/datalab" + "-" + digest[:12]) + ".gz"
    payloads = []
    with tarfile.open(args.package) as bundle:
        manifest, = json.load(bundle.extractfile("manifest.json"))
        for layer in manifest["Layers"]:
            with tarfile.open(fileobj=bundle.extractfile(layer)) as contents:
                for member in contents:
                    if member.name == "package.yaml":
                        payloads.append(contents.extractfile(member).read())
    payload, = payloads
    command = ["kubectl", "--kubeconfig", args.kubeconfig, "--context", args.context]

    def kube(*values, body=None):
        result = subprocess.run([*command, *values], input=json.dumps(body) if body else None,
                                capture_output=True, text=True, timeout=180, check=True)
        return result.stdout

    namespace = "crossplane"
    config = {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {
        "name": "test-datalab-candidate", "namespace": namespace},
        "binaryData": {key: base64.b64encode(gzip.compress(payload, mtime=0)).decode()}}
    kube("apply", "-f", "-", body=config)
    deployment = json.loads(kube("get", "deployment/crossplane", "-n", namespace, "-o", "json"))
    pod = deployment["spec"]["template"]["spec"]
    container = next(c for c in pod["containers"] if c["name"] == "crossplane")
    container["volumeMounts"] = [mount for mount in container.get("volumeMounts", [])
                                 if mount["name"] != "test-candidate"] + [{"name": "test-candidate",
        "mountPath": "/cache/xpkg/" + key, "subPath": key, "readOnly": True}]
    pod["volumes"] = [volume for volume in pod["volumes"] if volume["name"] != "test-candidate"] + [
        {"name": "test-candidate", "configMap": {"name": "test-datalab-candidate"}}]
    patch = {"spec": {"template": {"spec": {"containers": pod["containers"], "volumes": pod["volumes"]}}}}
    kube("patch", "deployment/crossplane", "-n", namespace, "--type=merge", "--patch", json.dumps(patch))
    kube("rollout", "status", "deployment/crossplane", "-n", namespace, "--timeout=150s")
    kube("apply", "-f", "-", body={"apiVersion": "pkg.crossplane.io/v1", "kind": "Configuration",
         "metadata": {"name": "test-datalab-candidate"}, "spec": {"package": reference,
         "packagePullPolicy": "Never", "revisionHistoryLimit": 0}})
    expected = yaml.safe_load((ROOT / "composition.yaml").read_text())
    deadline = time.monotonic() + 150
    while True:
        installed = json.loads(kube("get", "configuration.pkg.crossplane.io/test-datalab-candidate", "-o", "json"))
        current = installed.get("status", {}).get("currentRevision")
        if current:
            value = kube("get", "configurationrevision.pkg.crossplane.io/" + current, "--ignore-not-found", "-o", "json")
            revision = json.loads(value) if value else {}
            value = kube("get", "composition/" + expected["metadata"]["name"], "--ignore-not-found", "-o", "json")
            actual = json.loads(value) if value else {}
            healthy = any(c["type"] == "Healthy" and c["status"] == "True"
                          for c in installed.get("status", {}).get("conditions", []))
            owned = any(owner.get("kind") == "ConfigurationRevision" and owner.get("name") == current
                        and owner.get("controller") is True for owner in actual.get("metadata", {}).get("ownerReferences", []))
            if (healthy and revision.get("spec", {}).get("image") == reference and owned
                    and actual.get("spec") == expected["spec"]):
                break
        assert time.monotonic() < deadline, "The requested package revision and Composition did not become ready"
        time.sleep(2)
    print("PASS saved Configuration installs in Kind at digest " + digest, flush=True)


if __name__ == "__main__":
    main()
