#!/usr/bin/env python3
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Wait for managed records and their protection objects to leave the claim namespace."""

import argparse
import json
from pathlib import Path
import subprocess
import time


RESOURCES = "managed,usages.protection.crossplane.io,providerconfigs.kubernetes.m.crossplane.io"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("kubeconfig", "context", "datalab"):
        parser.add_argument("--" + field, required=True)
    parser.add_argument("--instance")
    parser.add_argument("--capture", type=Path)
    parser.add_argument("--records", type=Path)
    args = parser.parse_args()
    command = ["kubectl", "--kubeconfig", args.kubeconfig, "--context", args.context,
               "--namespace", "workspace"]

    def records(resource, selector=None):
        values = [*command, "get", resource, "-o", "json"]
        if selector:
            values += ["--selector", selector]
        result = subprocess.run(values, capture_output=True, text=True, check=True, timeout=60)
        return json.loads(result.stdout)["items"]

    def identity(body):
        return (body["apiVersion"], body["kind"], body["metadata"]["name"])

    selector = "crossplane.io/composite=" + args.datalab
    if args.capture:
        bodies = records(RESOURCES, selector)
        selected = [body for body in bodies if not args.instance or body["metadata"].get(
            "labels", {}).get("datalabs.versioneer.at/vcluster") == args.instance]
        names = {body["metadata"]["name"] for body in selected}
        selected += [body for body in bodies if body["kind"] == "Usage" and any(
            body["spec"].get(field, {}).get("resourceRef", {}).get("name") in names
            for field in ("of", "by"))]
        providers = []
        for body in selected:
            target = body.get("spec", {}).get("forProvider", {}).get("manifest", body)
            if target.get("kind") == "ProviderConfig":
                providers.append(target["metadata"]["name"])
        assert selected, "No managed records were found for the cleanup check"
        args.capture.write_text(json.dumps({"identities": [identity(b) for b in selected], "providers": providers}))
        return
    saved = json.loads(args.records.read_text()) if args.records else {"identities": [], "providers": []}
    expected = {tuple(item) for item in saved["identities"]}
    # Do not list unrelated provider APIs while the captured resources are deleted.
    watched = ",".join(sorted({kind.lower() + "." + api.split("/")[0]
                               for api, kind, _ in expected})) if args.records else RESOURCES
    deadline, report = time.monotonic() + 600, 0
    while True:
        bodies = records(watched, selector)
        pending = [body for body in bodies if (identity(body) in expected if args.records else True)]
        if args.records:
            usages = records("providerconfigusages.kubernetes.m.crossplane.io")
            pending += [body for body in usages if body.get("providerConfigRef", {}).get("name") in saved["providers"]]
            pending += [body for body in records("providerconfigs.kubernetes.m.crossplane.io")
                        if body["metadata"]["name"] in saved["providers"]]
        if not pending:
            print("PASS managed records, Usage objects, and provider users cleared for " + args.datalab, flush=True)
            return
        now = time.monotonic()
        names = [body["kind"] + "/" + body["metadata"]["name"] for body in pending]
        if now >= report:
            print(f"Waiting for cleanup ({len(names)} records): " + ", ".join(names[:5])
                  + (", ..." if len(names) > 5 else ""), flush=True)
            report = now + 30
        assert now < deadline, "Managed records remain after deletion: " + ", ".join(names)
        time.sleep(3)


if __name__ == "__main__":
    main()
