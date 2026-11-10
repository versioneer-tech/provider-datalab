#!/usr/bin/env python3
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Check published service credentials and namespace-limited Secret access."""

import argparse
import json
import subprocess
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kubeconfig", required=True)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--datalab", required=True)
    parser.add_argument("--deleted", action="store_true")
    args = parser.parse_args()
    command = ["kubectl", "--kubeconfig", args.kubeconfig, "--context", "kind-provider-datalab-it"]
    reader = "verify-connection-reader"
    identity = f"system:serviceaccount:{args.namespace}:{reader}"

    def kube(*arguments, body=None, impersonate=False):
        result = subprocess.run(command + (["--as", identity] if impersonate else []) + list(arguments),
                                input=json.dumps(body) if body is not None else None,
                                capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise AssertionError("Connection publication check failed: " + " ".join(arguments[:3]))
        return json.loads(result.stdout) if arguments[0] == "get" else None

    def get(kind, name=None, namespace=None, impersonate=False):
        return kube("get", kind, *([name] if name else []), "--namespace", namespace or args.namespace,
                    "-o", "json", impersonate=impersonate)

    def wait_for(check):
        deadline = time.monotonic() + 180
        while True:
            try:
                check()
                return
            except AssertionError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(2)

    def published():
        return [body for body in kube("get", "secrets", "--namespace", args.namespace,
                                     "--selector", "datalabs.versioneer.at/name=" + args.datalab, "-o", "json")["items"]
                if body["metadata"].get("labels", {}).get("datalabs.versioneer.at/name") == args.datalab
                and body["metadata"].get("labels", {}).get("datalabs.versioneer.at/connection")]

    if args.deleted:
        def removed():
            assert not published(), "Published Secrets survived Datalab deletion"
        wait_for(removed)
        print("PASS published connection Secrets are removed with the Datalab", flush=True)
        return

    kube("apply", "-f", "-", "-o", "json", body={"apiVersion": "v1", "kind": "List", "items": [
        {"apiVersion": "v1", "kind": "ServiceAccount", "metadata": {"name": reader, "namespace": args.namespace}},
        {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "Role",
         "metadata": {"name": reader, "namespace": args.namespace},
         "rules": [{"apiGroups": [""], "resources": ["secrets"], "verbs": ["get"]}]},
        {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "RoleBinding",
         "metadata": {"name": reader, "namespace": args.namespace},
         "roleRef": {"apiGroup": "rbac.authorization.k8s.io", "kind": "Role", "name": reader},
         "subjects": [{"kind": "ServiceAccount", "name": reader, "namespace": args.namespace}]},
    ]})

    def current():
        xr = get("datalabs.versioneer.at", args.datalab)
        sources = kube("get", "objects.kubernetes.m.crossplane.io", "--namespace", args.namespace,
                       "--selector", "crossplane.io/composite=" + args.datalab, "-o", "json")["items"]
        connections = [c for c in xr["status"].get("connections", [])
                       if c["type"] in ("postgres", "mongo", "redis", "custom")]
        assert connections and all(c["ready"] for c in connections), "Service publication is not ready"
        for connection in connections:
            kind, name, ref = connection["type"], connection["name"], connection["secretRef"]
            assert ref["namespace"] == args.namespace
            secret = get("secret", ref["name"], impersonate=True)
            assert secret["metadata"]["ownerReferences"] == [{
                "apiVersion": xr["apiVersion"], "kind": "Datalab", "name": args.datalab,
                "uid": xr["metadata"]["uid"], "controller": True, "blockOwnerDeletion": True,
            }]
            source_name = {"postgres": f"{name}-pguser-postgres", "mongo": f"{name}-mongodb-auth",
                           "redis": f"{name}-redis-auth", "custom": name}[kind]
            prefix = {"postgres": "observe-database-secret-", "mongo": "observe-mongodb-auth-secret-",
                      "redis": "observe-redis-auth-secret-", "custom": "observe-custom-secret-"}[kind]
            matches = [o["spec"]["forProvider"]["manifest"]["metadata"] for o in sources
                       if o["metadata"].get("labels", {}).get("crossplane.io/composite") == args.datalab
                       and o["metadata"].get("annotations", {}).get("crossplane.io/composition-resource-name", "").startswith(prefix)
                       and o["spec"]["forProvider"]["manifest"].get("metadata", {}).get("name") == source_name]
            assert len(matches) == 1, "Source observer is missing or ambiguous"
            source = get("secret", source_name, matches[0]["namespace"])
            data = source["data"]
            if kind != "custom":
                fields = {"host", "port", "user", "password", "dbname", "uri"} if kind == "postgres" else {"user", "password"}
                data = {key: value for key, value in data.items() if key in fields}
            assert secret.get("data") == data, "Published credentials differ from the current source"
            if matches[0]["namespace"] != args.namespace:
                denied = subprocess.run(command + ["--as", identity, "get", "secret", source_name,
                                        "--namespace", matches[0]["namespace"], "-o", "name"],
                                        capture_output=True, text=True, timeout=30)
                assert denied.returncode != 0 and "Forbidden" in denied.stderr, "Reader has access outside its namespace"

    wait_for(current)
    kube("delete", "serviceaccount,role,rolebinding", reader, "--namespace", args.namespace)
    print("PASS current service credentials resolve with Secret get permission confined to the Datalab namespace", flush=True)


if __name__ == "__main__":
    main()
