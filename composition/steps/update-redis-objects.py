# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

import base64
import hashlib

from crossplane.function.proto.v1 import run_function_pb2 as fnv1
from crossplane.function import response

from composition.helpers import (
    _extract_manifest,
    _resource_name,
    _extract_data,
    _safe_str,
    _string_value,
    _strong_token,
    _stores,
    _to_dict,
)
from composition.render import _render_template


BACKUP_SCRIPT = _embedded_script("scripts/redis-snapshot.py")
SNAPSHOT_SCRIPT = _embedded_script("scripts/volume-snapshot.py")


def compose(req: fnv1.RunFunctionRequest, rsp: fnv1.RunFunctionResponse):
    xr = _to_dict(req.observed.composite.resource)
    metadata = xr.get("metadata", {}) or {}
    spec = xr.get("spec", {}) or {}

    xr_name = metadata.get("name")
    xr_namespace = metadata.get("namespace") or "default"

    cache_stores = _stores(spec, "redis")
    if not isinstance(cache_stores, dict) or not cache_stores:
        return

    context = _to_dict(req.context)
    environment = context.get("apiextensions.crossplane.io/environment", {}) or {}
    images = environment.get("images") or {}
    redis_image = _safe_str(images.get("redis")) or "quay.io/opstree/redis:v7.2.17"
    backup_image = _safe_str(images.get("volumeSnapshot")) or "python:3.13-alpine"
    redis_env = environment.get("cacheStore") or {}
    redis_storage_class = _string_value(redis_env.get("storageClassName") or "")

    runtime_namespace = xr_name

    for store_key in sorted(list(cache_stores.keys())):
        if not isinstance(store_key, str) or not store_key.strip():
            continue
        store_cfg = cache_stores.get(store_key) or {}
        if not isinstance(store_cfg, dict):
            continue

        redis_storage = _string_value(store_cfg.get("storage") or "1Gi")
        if not redis_storage:
            continue
        store_name = store_key.strip()
        backups_enabled = store_cfg.get("backups") is True
        redis_password = _strong_token(
            f"{xr_name}:{store_name}:redis", suffix="", length=28
        )
        redis_auth_secret_name = f"{store_name}-redis-auth"
        redis_auth_secret = _render_template(
            req,
            "redis/auth-secret",
            redis_auth_secret_name=redis_auth_secret_name,
            runtime_namespace=runtime_namespace,
            redis_user="default",
            redis_password=redis_password,
        )
        auth_key = f"redis-auth-secret-{xr_name}-{store_name}"
        auth_body = _render_template(
            req,
            "redis/auth-object",
            auth_key=auth_key,
            xr_namespace=xr_namespace,
            redis_auth_secret=redis_auth_secret,
        )
        rsp.desired.resources[auth_key].resource.update(auth_body)

        redis_acl_secret_name = f"{store_name}-redis-acl"
        acl = f"user default on >{redis_password} ~* +@all\n"
        if backups_enabled:
            backup_password = _strong_token(f"{xr_name}:{store_name}:redis:backup")
            acl += f"user backup on >{backup_password} -@all +ping +info +bgsave +client|pause +client|unpause\n"
        encoded_acl = base64.b64encode(acl.encode()).decode()
        redis_acl_secret = _render_template(
            req,
            "redis/acl-secret",
            redis_acl_secret_name=redis_acl_secret_name,
            runtime_namespace=runtime_namespace,
            data_user_acl=encoded_acl,
        )
        acl_key = f"redis-acl-secret-{xr_name}-{store_name}"
        acl_body = _render_template(
            req,
            "redis/acl-object",
            acl_key=acl_key,
            xr_namespace=xr_namespace,
            redis_acl_secret=redis_acl_secret,
        )
        rsp.desired.resources[acl_key].resource.update(acl_body)
        # The operator mounts the ACL file with subPath, so changes need a restart.
        observed_acl = _extract_data(req, rsp, acl_key).get("user.acl") or encoded_acl
        acl_checksum = hashlib.sha256(observed_acl.encode()).hexdigest()

        pvc_spec = {
            "accessModes": ["ReadWriteOnce"],
            "resources": {"requests": {"storage": redis_storage}},
        }
        if redis_storage_class:
            pvc_spec["storageClassName"] = redis_storage_class

        storage = {
            "volumeClaimTemplate": {
                "metadata": {},
                "spec": pvc_spec,
            },
            "volumeMount": {},
        }
        redis_manifest = _render_template(
            req,
            "redis/store",
            redis_image=redis_image,
            store_name=store_name,
            runtime_namespace=runtime_namespace,
            redis_auth_secret_name=redis_auth_secret_name,
            redis_acl_secret_name=redis_acl_secret_name,
            redis_acl_checksum=acl_checksum,
            storage=storage,
        )

        key = f"redis-cache-{xr_name}-{store_name}"
        body = _render_template(
            req,
            "redis/store-object",
            key=key,
            xr_namespace=xr_namespace,
            redis_manifest=redis_manifest,
        )
        rsp.desired.resources[key].resource.update(body)

        if backups_enabled:
            backup_name = f"redis-{store_name}-backup"
            backup_secret_name = f"{store_name}-redis-backup-auth"
            backup_secret = _render_template(
                req,
                "redis/auth-secret",
                redis_auth_secret_name=backup_secret_name,
                runtime_namespace=runtime_namespace,
                redis_user="backup",
                redis_password=backup_password,
            )
            snapshot_class = redis_env.get("snapshotClassName") or (environment.get("volumes") or {}).get("snapshotClassName")
            retention = redis_env.get("maxSnapshots", 4)
            if not isinstance(snapshot_class, str) or not snapshot_class.strip():
                response.fatal(rsp, "Redis backups require data.cacheStore.snapshotClassName or data.volumes.snapshotClassName.")
                return
            if (isinstance(retention, bool) or not isinstance(retention, (int, float))
                    or retention != int(retention) or not 1 <= retention <= 100):
                response.fatal(rsp, "data.cacheStore.maxSnapshots must be an integer from 1 to 100.")
                return
            pod = _extract_manifest(req.observed.resources.get(f"redis-pod-{xr_name}-{store_name}"))
            volumes = {v["name"]: v.get("persistentVolumeClaim", {}).get("claimName")
                       for v in (pod.get("spec") or {}).get("volumes", [])}
            claims = {volumes.get(m["name"]) for c in (pod.get("spec") or {}).get("containers", [])
                      for m in c.get("volumeMounts", []) if m["mountPath"] == "/data"}
            claim = next(iter(claims)) if len(claims) == 1 and None not in claims else "unbound"
            resources = _render_template(
                req, "redis/backup-cronjob", target=runtime_namespace, pvc_name=claim,
                volume_name=store_name, backup_name=backup_name,
                backup_binding=_resource_name(runtime_namespace, backup_name),
                snapshot_class=snapshot_class, max_snapshots=str(int(retention)),
                schedule=redis_env.get("schedule") or "0 1 * * *",
                backup_script=BACKUP_SCRIPT, snapshot_script=SNAPSHOT_SCRIPT,
                backup_image=backup_image, backup_secret_name=backup_secret_name,
                pod_name=store_name + "-0", suspended=claim == "unbound",
            )["resources"]
            resources["auth-secret"] = backup_secret
            resources["class"] = {
                "apiVersion": "snapshot.storage.k8s.io/v1", "kind": "VolumeSnapshotClass",
                "metadata": {"name": snapshot_class},
            }
            for resource_type, manifest in resources.items():
                backup_key = f"redis-backup-{resource_type}-{xr_name}-{store_name}"
                readiness = ({"policy": "DeriveFromCelQuery", "celQuery": "object.deletionPolicy == 'Delete'"}
                             if resource_type == "class" else {"policy": "SuccessfulCreate"})
                backup_body = _render_template(
                    req, "common/object", key=backup_key, xr_namespace=xr_namespace,
                    manifest=manifest, readiness=readiness,
                )
                if resource_type == "class":
                    backup_body["spec"]["managementPolicies"] = ["Observe"]
                rsp.desired.resources[backup_key].resource.update(backup_body)

        pod_key = f"redis-pod-{xr_name}-{store_name}"
        pod_body = _render_template(
            req,
            "common/pod-observer",
            pod_key=pod_key,
            xr_namespace=xr_namespace,
            pod_name=f"{store_name}-0",
            runtime_namespace=runtime_namespace,
        )
        rsp.desired.resources[pod_key].resource.update(pod_body)
