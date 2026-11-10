# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

import base64
import hashlib

from crossplane.function.proto.v1 import run_function_pb2 as fnv1

from composition.helpers import (
    _backup_enabled,
    _extract_data,
    _safe_str,
    _string_value,
    _strong_token,
    _to_dict,
)
from composition.render import _render_template


def compose(req: fnv1.RunFunctionRequest, rsp: fnv1.RunFunctionResponse):
    xr = _to_dict(req.observed.composite.resource)
    metadata = xr.get("metadata", {}) or {}
    spec = xr.get("spec", {}) or {}

    xr_name = metadata.get("name")
    xr_namespace = metadata.get("namespace") or "default"

    cache_stores = spec.get("cacheStores")
    if not isinstance(cache_stores, dict) or not cache_stores:
        return

    context = _to_dict(req.context)
    environment = context.get("apiextensions.crossplane.io/environment", {}) or {}
    images = environment.get("images") or {}
    redis_image = _safe_str(images.get("redis")) or "quay.io/opstree/redis:v7.0.15"
    backup_image = _safe_str(images.get("redisBackup")) or "redis:7.0.15"
    redis_env = environment.get("cacheStore") or {}
    redis_storage_class = _string_value(redis_env.get("storageClassName") or "")
    backup_storage_class = _string_value(redis_env.get("backupStorageClassName") or "")

    observed = getattr(req.observed, "resources", None) or {}
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
        backup_storage = _string_value(store_cfg.get("backupStorage") or "0")
        backups_enabled = _backup_enabled(backup_storage)
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
            acl += f"user backup on >{backup_password} -@all +ping +replconf +sync\n"
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
        observed_acl = _extract_data(observed.get(acl_key)).get("user.acl") or encoded_acl
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
            backup_vcs = {
                "accessModes": ["ReadWriteOnce"],
                "resources": {"requests": {"storage": backup_storage}},
            }
            if backup_storage_class:
                backup_vcs["storageClassName"] = backup_storage_class
            backup_pvc = _render_template(
                req,
                "redis/backup-pvc",
                backup_name=backup_name,
                runtime_namespace=runtime_namespace,
                backup_vcs=backup_vcs,
            )
            backup_job = _render_template(
                req,
                "redis/backup-cronjob",
                redis_image=backup_image,
                backup_name=backup_name,
                runtime_namespace=runtime_namespace,
                backup_secret_name=backup_secret_name,
                backup_host=store_name,
            )
            for resource_type, manifest in (
                ("auth-secret", backup_secret),
                ("pvc", backup_pvc),
                ("cronjob", backup_job),
            ):
                backup_key = f"redis-backup-{resource_type}-{xr_name}-{store_name}"
                backup_body = _render_template(
                    req,
                    "common/object",
                    key=backup_key,
                    xr_namespace=xr_namespace,
                    manifest=manifest,
                    readiness={"policy": "SuccessfulCreate"},
                )
                if resource_type == "pvc":
                    # Keep completed backups when the schedule is disabled.
                    backup_body["spec"]["managementPolicies"] = [
                        "Observe", "Create", "Update", "LateInitialize"
                    ]
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
