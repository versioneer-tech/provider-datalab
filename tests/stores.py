# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Check store settings and the PostgreSQL runtime namespace."""

import base64
from copy import deepcopy
from pathlib import Path

import yaml

from render import arguments, environment, manifest, render


def main():
    args = arguments()
    env = environment()
    refs = {"parentName": "default", "parentNamespace": "contour", "sectionName": "postgres-passthrough"}
    env["data"]["database"] = {"tlsRoute": refs}
    stores = {"documentStore": "mongodb-community-s-jeff-prod", "cacheStore": "redis-cache-s-jeff-prod"}
    for setting in stores:
        env["data"][setting] = {"storageClassName": f"test-{setting}"}
    observed = list(yaml.safe_load_all(Path("tests/observed/002-lab.yaml").read_text()))
    resources = render(args, env, "examples/base/002-lab.yaml", observed, include_composite=True)
    route = manifest(resources, "db-tlsroute-s-jeff-pg0")
    assert route["kind"] == "TLSRoute"
    assert route["spec"]["parentRefs"] == [dict(name=refs["parentName"], namespace=refs["parentNamespace"],
                                                sectionName=refs["sectionName"])]
    for setting, name in stores.items():
        store = manifest(resources, name)
        assert f"test-{setting}" in yaml.safe_dump(store["spec"])
    for name in ("observe-database-secret-s-jeff-pg0", "db-postgrescluster-s-jeff-pg0"):
        assert manifest(resources, name)["metadata"]["namespace"] == "s-jeff"
    assert "secret-s-jeff-datalab" not in resources
    connections = resources["composite"]["status"]["connections"]
    assert {c["type"] for c in connections} == {"s3", "postgres", "mongo", "redis"}
    assert all(set(c) <= {"name", "type", "ready", "endpoint", "secretRef"} for c in connections)
    print("PASS store StorageClasses, PostgreSQL route, and runtime namespace", flush=True)

    published = []
    for connection in connections:
        assert not connection["ready"]
        key = f"connection-{connection['secretRef']['name']}"
        if key not in resources:
            continue
        secret = deepcopy(resources[key])
        assert secret["metadata"]["namespace"] == connection["secretRef"]["namespace"]
        secret["data"] = {
            key: base64.b64encode(value.encode()).decode()
            for key, value in secret.pop("stringData").items()
        }
        published.append(secret)
    current = render(args, env, "examples/base/002-lab.yaml", observed + published,
                     include_composite=True)
    for connection in current["composite"]["status"]["connections"]:
        assert connection["ready"], connection

    rotated = deepcopy(observed)
    for item in rotated:
        if item["metadata"]["name"] == "observe-storage-secret-s-jeff":
            item["status"]["atProvider"]["manifest"]["data"]["AWS_SECRET_ACCESS_KEY"] = (
                base64.b64encode(b"rotated-storage-key").decode()
            )
    updated = render(args, env, "examples/base/002-lab.yaml", rotated + published,
                     include_composite=True)
    states = {c["type"]: c["ready"] for c in updated["composite"]["status"]["connections"]}
    assert states == {"s3": False, "postgres": True, "mongo": True, "redis": True}
    assert updated["connection-s-jeff-s3"]["stringData"]["AWS_SECRET_ACCESS_KEY"] == "rotated-storage-key"
    print("PASS connection readiness waits for current credentials and detects rotation", flush=True)

    source = yaml.safe_load(Path("examples/base/002-lab.yaml").read_text())
    del source["spec"]["cacheStores"]
    reduced = render(args, env, source, observed + published, include_composite=True)
    assert not any(c["type"] == "redis" for c in reduced["composite"]["status"]["connections"])
    assert "connection-s-jeff-redis-prod" not in reduced
    print("PASS removing a store removes its connection and Secret", flush=True)

    without_storage = [item for item in observed if item["metadata"]["name"] != "observe-storage-secret-s-jeff"]
    independent = render(args, env, "examples/base/002-lab.yaml", without_storage)
    assert "connection-s-jeff-postgres-pg0" in independent
    assert "connection-s-jeff-s3" not in independent
    print("PASS database connections do not depend on storage credentials", flush=True)


if __name__ == "__main__":
    main()
