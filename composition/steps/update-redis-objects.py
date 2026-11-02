# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

from crossplane.function.proto.v1 import run_function_pb2 as fnv1
from google.protobuf import json_format as jf
import base64
import hashlib


def _to_dict(s):
    return {} if s is None else jf.MessageToDict(s, preserving_proto_field_name=True)


def _extract_manifest(objres):
    if not objres or not getattr(objres, "resource", None):
        return {}
    od = _to_dict(objres.resource)
    atp = (od.get("status") or {}).get("atProvider") or {}
    m1 = atp.get("manifest") or {}
    m2 = (atp.get("raw") or {}).get("manifest") or {}
    return (m1 or m2) or {}


def _safe_str(v):
    return str(v).strip()


def _strong_token(seed):
    d = hashlib.sha256(seed.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(d).decode("ascii").rstrip("=")[:28]


def compose(req: fnv1.RunFunctionRequest, rsp: fnv1.RunFunctionResponse):
    xr = _to_dict(req.observed.composite.resource)
    meta = xr.get("metadata", {}) or {}
    spec = xr.get("spec", {}) or {}

    xr_name = meta.get("name")
    xr_namespace = meta.get("namespace") or "default"

    cache_stores = spec.get("cacheStores")
    if not isinstance(cache_stores, dict) or not cache_stores:
        return

    ctx = _to_dict(req.context)
    env = ctx.get("apiextensions.crossplane.io/environment", {}) or {}
    redis_env = env.get("cacheStore") or {}
    redis_storage_class = _safe_str(redis_env.get("storageClassName") or "")

    observed = getattr(req.observed, "resources", None) or {}
    env_key = f"workshopenvironment-{xr_name}"
    env_manifest = _extract_manifest(observed.get(env_key))

    educates_status = (env_manifest.get("status") or {}).get("educates") or {}
    workshop_ns = _safe_str(educates_status.get("namespace") or xr_name)

    if not workshop_ns:
        return

    for store_key in sorted(list(cache_stores.keys())):
        if not isinstance(store_key, str) or not store_key.strip():
            continue
        store_cfg = cache_stores.get(store_key) or {}
        if not isinstance(store_cfg, dict):
            continue

        redis_storage = _safe_str(store_cfg.get("storage") or "1Gi")
        if not redis_storage:
            continue
        store_name = store_key.strip()
        redis_password = _strong_token(f"{xr_name}:{store_name}:redis")
        redis_auth_secret_name = f"{store_name}-redis-auth"
        redis_auth_secret = _render_template(
            req,
            "redis/auth-secret",
            redis_auth_secret_name=redis_auth_secret_name,
            workshop_ns=workshop_ns,
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
            workshop_ns=workshop_ns,
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
            workshop_ns=workshop_ns,
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
            "redis/pod-observer",
            pod_key=pod_key,
            xr_namespace=xr_namespace,
            pod_name=f"{store_name}-0",
            workshop_ns=workshop_ns,
        )
        rsp.desired.resources[pod_key].resource.update(pod_body)
