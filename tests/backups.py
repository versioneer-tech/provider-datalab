#!/usr/bin/env python3
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Check backup enablement and preservation of completed archives."""

import base64
from copy import deepcopy
from pathlib import Path
import subprocess
import tempfile

import yaml

from render import arguments, load, manifest, render


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
    completed = {path.name: path.read_text() for path in backup.iterdir()}
    command = ["/bin/sh", "-ec", script.replace("/backup/", f"{backup}/").replace("find /backup ", f"find {backup} ")]
    environment = {"PATH": f"{binaries}:/usr/bin:/bin", "BACKUP_HOST": "unused", "BACKUP_USER": "unused"}
    result = subprocess.run(command, env=environment, capture_output=True, text=True)
    assert result.returncode != 0
    assert {path.name: path.read_text() for path in backup.iterdir()} == completed, "A failed dump changed completed backups"
    dump.write_text(fake_dump + "exit 0\n")
    if tool == "redis-cli":
        checker.write_text("#!/bin/sh\nexit 1\n")
        result = subprocess.run(command, env=environment, capture_output=True, text=True)
        assert result.returncode != 0
        assert {path.name: path.read_text() for path in backup.iterdir()} == completed, "An invalid RDB changed completed backups"
        checker.write_text("#!/bin/sh\nexit 0\n")
    subprocess.run(command, env=environment, check=True)
    archives = list(backup.glob(f"dump-*.{suffix}"))
    assert len(archives) == 4
    assert not (backup / f"dump-20000101T010000Z.{suffix}").exists()
    assert not (backup / f"dump-20000102T010000Z.{suffix}").exists()
    assert not (backup / "dump.partial").exists()


def main():
    args = arguments()
    original = load("examples/base/002-lab.yaml")
    environments = list(yaml.safe_load_all(Path("tests/environmentconfig.yaml").read_text()))
    environment = next(item for item in environments if item["metadata"]["name"] == "datalab")
    environment["data"].setdefault("documentStore", {})["backupStorageClassName"] = "backup-test"
    environment["data"].setdefault("cacheStore", {})["backupStorageClassName"] = "backup-test"
    for size in (None, "0Gi", "1Gi"):
        source = deepcopy(original)
        for field, name in (("databases", "pg0"), ("documentStores", "prod"), ("cacheStores", "prod")):
            if size is None:
                source["spec"][field][name].pop("backupStorage", None)
            else:
                source["spec"][field][name]["backupStorage"] = size
        resources = render(args, environment, source, "tests/observed/002-lab.yaml")
        enabled = size == "1Gi"
        cluster = manifest(resources, "db-postgrescluster-s-jeff-pg0")
        assert ("backups" in cluster["spec"]) == enabled
        query = resources["db-postgrescluster-s-jeff-pg0"]["spec"]["readiness"]["celQuery"]
        assert ("pgbackrest" in query) == enabled
        assert cluster["metadata"]["namespace"] == "s-jeff"
        mongo = manifest(resources, "mongodb-community-s-jeff-prod")
        backup_users = [user for user in mongo["spec"]["users"] if user["name"] == "prod-backup"]
        assert bool(backup_users) == enabled
        acl = base64.b64decode(manifest(resources, "redis-acl-secret-s-jeff-prod")["data"]["user.acl"]).decode()
        assert ("user backup " in acl) == enabled
        if enabled:
            assert backup_users[0]["roles"] == [{"name": "backup", "db": "admin"}]
            assert "-@all +ping +replconf +sync" in acl
        for store in ("mongodb", "redis"):
            for kind in ("pvc", "cronjob"):
                assert (f"{store}-backup-{kind}-s-jeff-prod" in resources) == enabled
            if not enabled:
                assert not any(name.startswith(f"{store}-backup-") for name in resources)
                continue
            pvc_name = f"{store}-backup-pvc-s-jeff-prod"
            pvc = manifest(resources, pvc_name)
            assert pvc["metadata"]["namespace"] == cluster["metadata"]["namespace"]
            assert pvc["spec"]["resources"]["requests"]["storage"] == size
            assert pvc["spec"]["storageClassName"] == "backup-test"
            assert "Delete" not in resources[pvc_name]["spec"]["managementPolicies"]
            job = manifest(resources, f"{store}-backup-cronjob-s-jeff-prod")
            container = job["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
            with tempfile.TemporaryDirectory(prefix="test-backups-") as directory:
                if store == "mongodb":
                    check_archive_retention(container["args"][0], Path(directory) / "mongo")
                else:
                    check_archive_retention(container["args"][0], Path(directory) / "redis", "redis-cli", "rdb")
        print(f"PASS PostgreSQL, MongoDB, and Redis backupStorage={size}", flush=True)


if __name__ == "__main__":
    main()
