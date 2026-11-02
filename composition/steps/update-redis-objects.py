# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

from crossplane.function.proto.v1 import run_function_pb2 as fnv1

from composition.helpers import (
    _extract_manifest,
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
    redis_env = environment.get("cacheStore") or {}
    redis_storage_class = _string_value(redis_env.get("storageClassName") or "")

    observed = getattr(req.observed, "resources", None) or {}
    env_key = f"workshopenvironment-{xr_name}"
    environment_manifest = _extract_manifest(observed.get(env_key))

    educates_status = (environment_manifest.get("status") or {}).get("educates") or {}
    workshop_namespace = _string_value(educates_status.get("namespace") or xr_name)

    if not workshop_namespace:
        return

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
        redis_password = _strong_token(
            f"{xr_name}:{store_name}:redis", suffix="", length=28
        )
        redis_auth_secret_name = f"{store_name}-redis-auth"
        redis_auth_secret = _render_template(
            req,
            "redis/auth-secret",
            redis_auth_secret_name=redis_auth_secret_name,
            workshop_ns=workshop_namespace,
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
        redis_acl_secret = _render_template(
            req,
            "redis/acl-secret",
            redis_acl_secret_name=redis_acl_secret_name,
            workshop_ns=workshop_namespace,
            stringData_user_acl=f"user default on >{redis_password} ~* +@all\n",
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
            store_name=store_name,
            workshop_ns=workshop_namespace,
            redis_auth_secret_name=redis_auth_secret_name,
            redis_acl_secret_name=redis_acl_secret_name,
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

        pod_key = f"redis-pod-{xr_name}-{store_name}"
        pod_body = _render_template(
            req,
            "common/pod-observer",
            pod_key=pod_key,
            xr_namespace=xr_namespace,
            pod_name=f"{store_name}-0",
            workshop_ns=workshop_namespace,
        )
        rsp.desired.resources[pod_key].resource.update(pod_body)
