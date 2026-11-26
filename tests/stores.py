# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Check store settings and the PostgreSQL runtime namespace."""

import base64
import json
from pathlib import Path
import re

import yaml

from render import arguments, environment, load, manifest, render


def main():
    args = arguments()
    env = environment()
    refs = {"parentName": "default", "parentNamespace": "contour", "sectionName": "postgres-passthrough"}
    env["data"]["database"] = {"tlsRoute": refs, "snapshotClassName": "test-snapshots"}
    stores = {"cacheStore": "valkey-cache-s-jeff-cache"}
    for setting in stores:
        env["data"][setting] = {"storageClassName": f"test-{setting}", "snapshotClassName": "test-snapshots"}
    observed = list(yaml.safe_load_all(Path("tests/observed/002-lab.yaml").read_text()))
    resources = render(args, env, "examples/base/002-lab.yaml", observed)
    route = manifest(resources, "db-tlsroute-s-jeff-pg0")
    assert route["kind"] == "TLSRoute"
    assert route["spec"]["parentRefs"] == [dict(name=refs["parentName"], namespace=refs["parentNamespace"],
                                                sectionName=refs["sectionName"])]
    valkey_pvc = manifest(resources, "valkey-data-s-jeff-cache")
    assert valkey_pvc["spec"]["storageClassName"] == "test-cacheStore"
    workload = manifest(resources, stores["cacheStore"])
    container = workload["spec"]["template"]["spec"]["containers"][0]
    assert workload["kind"] == "StatefulSet"
    assert container["env"][0]["name"] == "VALKEYCLI_AUTH"
    for kind in ("startupProbe", "readinessProbe", "livenessProbe"):
        assert 'valkey-cli' in container[kind]["exec"]["command"][-1]
    assert "everysec" in container["args"] and "--aclfile" in container["args"]
    assert {volume["persistentVolumeClaim"]["claimName"] for volume in workload["spec"]["template"]["spec"]["volumes"]
            if "persistentVolumeClaim" in volume} == {valkey_pvc["metadata"]["name"]}
    resized = load("examples/base/002-lab.yaml")
    resized["spec"]["stores"]["cache"]["storage"] = "2Gi"
    expanded = render(args, env, resized, observed)
    assert manifest(expanded, "valkey-data-s-jeff-cache")["spec"]["resources"]["requests"]["storage"] == "2Gi"
    assert manifest(expanded, stores["cacheStore"]) == workload
    for name in ("observe-database-secret-s-jeff-pg0", "db-cluster-s-jeff-pg0"):
        assert manifest(resources, name)["metadata"]["namespace"] == "s-jeff"
    valkey = manifest(resources, "valkey-auth-secret-s-jeff-cache")
    assert base64.b64decode(valkey["data"]["user"]).decode() == "default"

    user_secrets = [body["spec"]["forProvider"]["manifest"] for body in resources.values()
                    if body.get("kind") == "Object"
                    and body.get("spec", {}).get("forProvider", {}).get("manifest", {}).get("type") == "kubernetes.io/basic-auth"]
    assert len(user_secrets) == 3
    assert len({secret["data"]["password"] for secret in user_secrets}) == 3
    chosen = user_secrets[0]
    chosen["data"]["password"] = base64.b64encode(b"test-chosen-password").decode()
    persistent = render(args, [env, chosen], "examples/base/002-lab.yaml", observed)
    current = next(body["spec"]["forProvider"]["manifest"] for body in persistent.values()
                   if body.get("kind") == "Object" and body.get("spec", {}).get("forProvider", {}).get("manifest", {}).get("metadata", {}).get("name") == chosen["metadata"]["name"])
    assert current["data"]["password"] == chosen["data"]["password"]
    print("PASS named PostgreSQL users have distinct passwords and retain stored credentials", flush=True)
    unusual = load("examples/base/002-lab.yaml")
    unusual["spec"]["users"] = ["person@example.test"]
    unusual["spec"]["stores"]["pg0"]["names"] = ["Sales Data", "postgres"]
    special = render(args, env, unusual, observed)
    databases = [body["spec"]["forProvider"]["manifest"] for body in special.values()
                 if body.get("kind") == "Object" and body.get("spec", {}).get("forProvider", {}).get("manifest", {}).get("kind") == "Database"]
    assert [database["spec"]["name"] for database in databases] == ["Sales Data"]
    assert re.fullmatch(r"[a-z0-9-]+", databases[0]["metadata"]["name"])
    assert special["connection-s-jeff-postgres-pg0"]["stringData"]["sales_data_url"].endswith("/Sales%20Data")
    account_secrets = [body["spec"]["forProvider"]["manifest"] for body in special.values()
                      if body.get("kind") == "Object" and body.get("spec", {}).get("forProvider", {}).get("manifest", {}).get("type") == "kubernetes.io/basic-auth"]
    assert len(account_secrets) == 1
    assert re.fullmatch(r"[a-z0-9-]+", account_secrets[0]["metadata"]["name"])
    assert base64.b64decode(account_secrets[0]["data"]["username"]).decode() == "person@example.test"
    print("PASS PostgreSQL keeps SQL names separate from Kubernetes resource names", flush=True)

    print("PASS Valkey credentials, store StorageClasses, PostgreSQL route, and runtime namespace", flush=True)
    grouped = load("examples/base/002-lab.yaml")
    grouped["spec"]["stores"]["cache"]["names"] = ["sessions", "jobs"]
    grouped["spec"]["stores"]["queue"] = {"type": "valkey", "storage": "1Gi"}
    grouped["spec"]["stores"]["pg0"].pop("names")
    grouped_resources = render(args, env, grouped, observed, include_composite=True)
    logical = {(item["type"], item["name"]): item.get("names")
               for item in grouped_resources["composite"]["status"]["connections"]}
    assert logical[("postgres", "pg0")] == logical[("valkey", "queue")] == ["default"]
    assert logical[("valkey", "cache")] == ["sessions", "jobs"]
    valkey_instances = [body["spec"]["forProvider"]["manifest"] for body in grouped_resources.values()
                       if body.get("kind") == "Object" and body.get("spec", {}).get("forProvider", {}).get("manifest", {}).get("kind") == "StatefulSet"]
    assert {item["metadata"]["name"] for item in valkey_instances} == {"cache", "queue"}
    assert json.loads(grouped_resources["connection-s-jeff-valkey-cache"]["stringData"]["prefixes"]) == {
        "sessions": "sessions:", "jobs": "jobs:"}
    database_names = [body["spec"]["forProvider"]["manifest"]["spec"]["name"] for body in grouped_resources.values()
                      if body.get("kind") == "Object" and body.get("spec", {}).get("forProvider", {}).get("manifest", {}).get("kind") == "Database"]
    assert database_names == ["default"]
    print("PASS typed store instances share logical names, publish Valkey prefixes, and default to one name", flush=True)
    env["data"]["images"] = {"valkey": "test-images/valkey:custom", "volumeSnapshot": "test-images/snapshot:custom"}
    resources = render(args, env, "examples/base/002-lab.yaml", observed)
    valkey_store = manifest(resources, stores["cacheStore"])["spec"]
    assert valkey_store["template"]["spec"]["containers"][0]["image"] == env["data"]["images"]["valkey"]
    job = manifest(resources, "valkey-backup-cronjob-s-jeff-cache")
    assert job["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]["image"] == env["data"]["images"]["volumeSnapshot"]
    print("PASS Valkey server and snapshot image overrides", flush=True)


if __name__ == "__main__":
    main()
