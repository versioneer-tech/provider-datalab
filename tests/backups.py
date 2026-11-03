#!/usr/bin/env python3
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Check backup enablement and preservation of completed archives."""

import argparse
import base64
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import tempfile

import yaml


def check_archive_retention(script, work, tool="mongodump", suffix="archive.gz"):
    work.mkdir()
    backup = work / "backup"
    backup.mkdir()
    binaries = work / "bin"
    binaries.mkdir()
    dump = binaries / tool
    if tool == "redis-cli":
        fake_dump = '#!/bin/sh\nfor output; do :; done\necho dump > "$output"\n'
        checker = binaries / "redis-check-rdb"
        checker.write_text("#!/bin/sh\nexit 0\n")
        checker.chmod(0o755)
    else:
        fake_dump = '#!/bin/sh\nfor arg; do case "$arg" in --archive=*) echo dump > "${arg#--archive=}";; esac; done\n'
    dump.write_text(fake_dump + "exit 1\n")
    dump.chmod(0o755)
    for index in range(5):
        (backup / f"dump-2000010{index + 1}T010000Z.{suffix}").write_text("old dump")
    completed = set(backup.iterdir())
    command = ["/bin/sh", "-ec", script.replace("/backup/", f"{backup}/").replace("find /backup ", f"find {backup} ")]
    environment = {"PATH": f"{binaries}:/usr/bin:/bin", "BACKUP_HOST": "unused", "BACKUP_USER": "unused"}
    result = subprocess.run(command, env=environment, capture_output=True, text=True)
    assert result.returncode != 0
    assert set(backup.iterdir()) == completed, "A failed dump changed completed backups"
    dump.write_text(fake_dump + "exit 0\n")
    if tool == "redis-cli":
        checker.write_text("#!/bin/sh\nexit 1\n")
        result = subprocess.run(command, env=environment, capture_output=True, text=True)
        assert result.returncode != 0
        assert set(backup.iterdir()) == completed, "An invalid RDB changed completed backups"
        checker.write_text("#!/bin/sh\nexit 0\n")
    subprocess.run(command, env=environment, check=True)
    archives = list(backup.glob(f"dump-*.{suffix}"))
    assert len(archives) == 4
    assert not (backup / f"dump-20000101T010000Z.{suffix}").exists()
    assert not (backup / f"dump-20000102T010000Z.{suffix}").exists()
    assert not (backup / "dump.partial").exists()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--functions", default="dependencies/functions.yaml")
    parser.add_argument("--network")
    args = parser.parse_args()
    original = yaml.safe_load(Path("examples/base/002-lab.yaml").read_text())
    environments = list(yaml.safe_load_all(Path("tests/environmentconfig.yaml").read_text()))
    environment = next(item for item in environments if item["metadata"]["name"] == "datalab")
    environment["data"].setdefault("documentStore", {})["backupStorageClassName"] = "backup-test"
    environment["data"].setdefault("cacheStore", {})["backupStorageClassName"] = "backup-test"
    with tempfile.TemporaryDirectory(prefix="xyz-backups-") as directory:
        work = Path(directory)
        environment_path = work / "environment.yaml"
        environment_path.write_text(yaml.safe_dump(environment))
        for size in (None, "0", "0Gi", "0.0Gi", "1Gi", "1e3"):
            source = deepcopy(original)
            for field, name in (("databases", "pg0"), ("documentStores", "prod"), ("cacheStores", "prod")):
                if size is None:
                    source["spec"][field][name].pop("backupStorage", None)
                else:
                    source["spec"][field][name]["backupStorage"] = size
            source_path = work / "datalab.yaml"
            source_path.write_text(json.dumps(source))
            result = subprocess.run(
                ["crossplane", "render", str(source_path), "composition.yaml", args.functions,
                 "--required-resources", str(environment_path),
                 "--observed-resources", "tests/observed/002-lab.yaml", "-x"]
                + (["--crossplane-docker-network", args.network] if args.network else []),
                capture_output=True, text=True, timeout=120,
            )
            assert result.returncode == 0, result.stderr
            resources = {item["metadata"]["name"]: item for item in yaml.safe_load_all(result.stdout)}

            def manifest(name):
                return resources[name]["spec"]["forProvider"]["manifest"]

            enabled = size in ("1Gi", "1e3")
            cluster = manifest("db-postgrescluster-s-jeff-pg0")
            assert cluster["spec"]["users"][0]["databases"] == ["dev", "prod"]
            assert ("backups" in cluster["spec"]) == enabled
            query = resources["db-postgrescluster-s-jeff-pg0"]["spec"]["readiness"]["celQuery"]
            assert ("pgbackrest" in query) == enabled
            workshop = yaml.safe_dump(manifest("workshop-s-jeff"))
            assert "pg0-primary" in workshop, "PostgreSQL service access was removed"
            mongo = manifest("mongodb-community-s-jeff-prod")
            backup_keys = [name for name in resources if name.startswith("mongodb-backup-")]
            assert len(backup_keys) == (3 if enabled else 0)
            assert len(mongo["spec"]["users"]) == (2 if enabled else 1)
            if enabled:
                pvc = manifest("mongodb-backup-pvc-s-jeff-prod")
                assert pvc["metadata"]["namespace"] == cluster["metadata"]["namespace"]
                assert pvc["spec"]["resources"]["requests"]["storage"] == size, pvc["spec"]
                assert pvc["spec"]["storageClassName"] == "backup-test"
                assert "Delete" not in resources["mongodb-backup-pvc-s-jeff-prod"]["spec"]["managementPolicies"]
                assert mongo["spec"]["users"][1]["roles"] == [{"name": "backup", "db": "admin"}]
                job = manifest("mongodb-backup-cronjob-s-jeff-prod")
                assert job["spec"]["concurrencyPolicy"] == "Forbid"
                container = job["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
                assert container["image"] == f"mongo:{mongo['spec']['version']}"
                assert "--oplog" in container["args"][0]
                assert "--config=/auth/config.yaml" in container["args"][0]
                if size == "1Gi":
                    check_archive_retention(container["args"][0], work / "mongo")
            redis = manifest("redis-cache-s-jeff-prod")
            redis_backups = [name for name in resources if name.startswith("redis-backup-")]
            assert len(redis_backups) == (3 if enabled else 0)
            acl = base64.b64decode(manifest("redis-acl-secret-s-jeff-prod")["data"]["user.acl"]).decode()
            assert ("user backup " in acl) == enabled
            if enabled:
                pvc = manifest("redis-backup-pvc-s-jeff-prod")
                assert pvc["metadata"]["namespace"] == redis["metadata"]["namespace"]
                assert pvc["spec"]["resources"]["requests"]["storage"] == size
                assert pvc["spec"]["storageClassName"] == "backup-test"
                assert "Delete" not in resources["redis-backup-pvc-s-jeff-prod"]["spec"]["managementPolicies"]
                assert "-@all +ping +replconf +sync" in acl
                job = manifest("redis-backup-cronjob-s-jeff-prod")
                container = job["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
                server_version = redis["spec"]["kubernetesConfig"]["image"].split(":")[-1].removeprefix("v")
                assert container["image"].split(":")[-1] == server_version
                auth = container["env"][1]["valueFrom"]["secretKeyRef"]
                assert auth == {"name": "prod-redis-backup-auth", "key": "password"}
                if size == "1Gi":
                    check_archive_retention(container["args"][0], work / "redis", "redis-cli", "rdb")
            print(f"PASS PostgreSQL, MongoDB, and Redis backupStorage={size}", flush=True)


if __name__ == "__main__":
    main()
