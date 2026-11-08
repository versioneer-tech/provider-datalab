# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Check store settings and the PostgreSQL runtime namespace."""

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
    for item in observed:
        if item["metadata"]["name"] == "workshopenvironment-s-jeff":
            item["status"]["atProvider"]["manifest"]["status"]["educates"]["namespace"] = "test-runtime"
    resources = render(args, env, "examples/base/002-lab.yaml", observed)
    route = manifest(resources, "db-tlsroute-s-jeff-pg0")
    assert route["kind"] == "TLSRoute"
    assert route["spec"]["parentRefs"] == [dict(name=refs["parentName"], namespace=refs["parentNamespace"],
                                                sectionName=refs["sectionName"])]
    for setting, name in stores.items():
        store = manifest(resources, name)
        assert f"test-{setting}" in yaml.safe_dump(store["spec"])
    for name in ("observe-database-secret-s-jeff-pg0", "db-postgrescluster-s-jeff-pg0"):
        assert manifest(resources, name)["metadata"]["namespace"] == "test-runtime"
    mongo = manifest(resources, "mongodb-auth-secret-s-jeff-prod")
    mongo_store = manifest(resources, stores["documentStore"])
    assert mongo["stringData"]["user"] == mongo_store["spec"]["users"][0]["name"] == "prod-app"
    redis = manifest(resources, "redis-auth-secret-s-jeff-prod")
    assert redis["stringData"]["user"] == "default"

    def backup_image(resources, store):
        return manifest(resources, f"{store}-backup-cronjob-s-jeff-prod")["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]["image"]

    print("PASS MongoDB and Redis credentials match their configured users", flush=True)
    print("PASS store StorageClasses, PostgreSQL route, and runtime namespace", flush=True)
    env["data"]["images"] = {"mongo": "test-images/mongo:8.0.13-ubi8", "mongoBackup": "test-images/mongo-tools:8.0.13",
                             "redis": "test-images/redis:custom", "redisBackup": "test-images/redis-tools:custom"}
    resources = render(args, env, "examples/base/002-lab.yaml", observed)
    mongo_store = manifest(resources, stores["documentStore"])["spec"]
    assert mongo_store["version"] == "8.0.13"
    assert mongo_store["statefulSet"]["spec"]["template"]["spec"]["containers"] == [
        {"name": "mongod", "image": env["data"]["images"]["mongo"]}]
    redis_store = manifest(resources, stores["cacheStore"])["spec"]
    assert redis_store["kubernetesConfig"]["image"] == redis_store["initContainer"]["image"] == env["data"]["images"]["redis"]
    assert backup_image(resources, "mongodb") == env["data"]["images"]["mongoBackup"]
    assert backup_image(resources, "redis") == env["data"]["images"]["redisBackup"]
    print("PASS store image overrides select server, init, and backup images and match the MongoDB version", flush=True)


if __name__ == "__main__":
    main()
