# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Check store settings and the PostgreSQL runtime namespace."""

import base64
import json
import hashlib
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
    route = manifest(resources, "db-tlsroute-s-jeff-postgres-pg0")
    assert route["kind"] == "TLSRoute"
    assert route["spec"]["parentRefs"] == [dict(name=refs["parentName"], namespace=refs["parentNamespace"],
                                                sectionName=refs["sectionName"])]
    valkey_pvc = manifest(resources, "valkey-data-s-jeff-cache")
    assert valkey_pvc["spec"]["storageClassName"] == "test-cacheStore"
    workload = manifest(resources, stores["cacheStore"])
    container = workload["spec"]["template"]["spec"]["containers"][0]
    assert workload["kind"] == "StatefulSet"
    assert workload["metadata"]["name"] == "valkey-cache"
    assert container["args"][container["args"].index("--maxmemory") + 1] == "256mb"
    assert container["args"][container["args"].index("--maxmemory-policy") + 1] == "noeviction"
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
    for name in ("observe-database-secret-s-jeff-pg0", "db-cluster-s-jeff-postgres-pg0"):
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
    assert {item["metadata"]["name"] for item in valkey_instances} == {"valkey-cache", "valkey-queue"}
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
    collision = load("examples/base/002-lab.yaml")
    collision["spec"]["stores"] = {
        "registry": {"type": "valkey", "storage": "1Gi"},
        "package-r": {"type": "valkey", "storage": "1Gi"},
        "vcluster-vc0": {"type": "valkey", "storage": "1Gi"},
        "valkey-registry": {"type": "postgres", "storage": "1Gi"},
    }
    env["data"]["registry"] = {"enabled": True}
    distinct = render(args, env, collision, observed)
    identities = []
    for body in distinct.values():
        if body.get("kind") != "Object" or body.get("spec", {}).get("managementPolicies") == ["Observe"]:
            continue
        target = body["spec"]["forProvider"]["manifest"]
        identities.append((target["apiVersion"], target["kind"], target["metadata"].get("namespace"), target["metadata"]["name"]))
    assert len(identities) == len(set(identities))
    print("PASS store names cannot collide with built-in services or other store types", flush=True)
    longest = load("examples/base/002-lab.yaml")
    longest["spec"]["stores"] = {
        "v" * 63: {"type": "valkey", "storage": "1Gi", "backups": True},
        "p" * 63: {"type": "postgres", "storage": "1Gi", "backups": True},
    }
    long_resources = render(args, env, longest, observed)
    schedules = [body["spec"]["forProvider"]["manifest"] for body in long_resources.values()
                 if body.get("kind") == "Object" and body["spec"]["forProvider"]["manifest"]["kind"] in ("CronJob", "ScheduledBackup")]
    assert len(schedules) == 2
    assert all(len(job["metadata"]["name"]) <= (52 if job["kind"] == "CronJob" else 63) for job in schedules)
    assert all(len(job["metadata"]["name"] + "-20000101000000") <= 63
               for job in schedules if job["kind"] == "ScheduledBackup")
    print("PASS maximum-length store names produce valid backup schedule names", flush=True)
    protected = load("examples/base/002-lab.yaml")
    protected["spec"]["stores"] = {"valkey": {"type": "valkey", "storage": "1Gi", "backups": True}}
    weak = []
    for suffix, seed, length in (
            ("auth", "s-jeff:valkey:valkey", 28),
            ("backup-auth", "s-jeff:valkey:valkey:backup:provider-datalab", 32)):
        password = base64.urlsafe_b64encode(hashlib.sha256(seed.encode()).digest()).decode().rstrip("=")[:length]
        weak.append({"apiVersion": "v1", "kind": "Secret", "metadata": {
            "name": "valkey-valkey-" + suffix, "namespace": "s-jeff"},
            "data": {"password": base64.b64encode(password.encode()).decode()}})
    secure = render(args, [env, *weak], protected, observed)
    for old in weak:
        current = next(body["spec"]["forProvider"]["manifest"] for body in secure.values()
                       if body.get("kind") == "Object" and body["spec"].get("managementPolicies") != ["Observe"]
                       and body["spec"]["forProvider"]["manifest"].get("metadata", {}).get("name") == old["metadata"]["name"])
        assert current["data"]["password"] != old["data"]["password"]
        assert len(base64.b64decode(current["data"]["password"])) == 43
    print("PASS the Valkey store replaces public-name password hashes when Secret names stay the same", flush=True)



if __name__ == "__main__":
    main()
