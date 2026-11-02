# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

from crossplane.function.proto.v1 import run_function_pb2 as fnv1
from google.protobuf import json_format as jf


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
    import hashlib
    import base64

    digest = hashlib.sha256((seed + ":provider-datalab").encode()).digest()
    token = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return token[:32]


def compose(req: fnv1.RunFunctionRequest, rsp: fnv1.RunFunctionResponse):
    xr = _to_dict(req.observed.composite.resource)
    meta = xr.get("metadata", {}) or {}
    spec = xr.get("spec", {}) or {}

    xr_name = meta.get("name")
    xr_namespace = meta.get("namespace") or "default"

    vector_stores = spec.get("vectorStores")
    if not isinstance(vector_stores, dict) or not vector_stores:
        return

    ctx = _to_dict(req.context)
    env = ctx.get("apiextensions.crossplane.io/environment", {}) or {}
    qdrant_env = env.get("vectorStore") or {}
    qdrant_storage_class = _safe_str(qdrant_env.get("storageClassName") or "")

    observed = getattr(req.observed, "resources", None) or {}
    env_key = f"workshopenvironment-{xr_name}"
    env_manifest = _extract_manifest(observed.get(env_key))

    educates_status = (env_manifest.get("status") or {}).get("educates") or {}
    workshop_ns = _safe_str(educates_status.get("namespace") or xr_name)

    if not workshop_ns:
        return

    for store_key in sorted(list(vector_stores.keys())):
        if not isinstance(store_key, str) or not store_key.strip():
            continue
        store_cfg = vector_stores.get(store_key) or {}
        if not isinstance(store_cfg, dict):
            continue

        qdrant_storage = _safe_str(store_cfg.get("storage") or "1Gi")
        if not qdrant_storage:
            continue
        store_name = store_key.strip()
        qdrant_auth_secret_name = f"{store_name}-qdrant-auth"
        qdrant_auth_secret = _render_template(
            req,
            "qdrant/auth-secret",
            qdrant_auth_secret_name=qdrant_auth_secret_name,
            workshop_ns=workshop_ns,
            stringData_apiKey=_strong_token(f"{xr_name}:{store_name}:qdrant:write"),
            stringData_readApiKey=_strong_token(f"{xr_name}:{store_name}:qdrant:read"),
        )
        auth_key = f"qdrant-auth-secret-{xr_name}-{store_name}"
        auth_body = _render_template(
            req,
            "qdrant/auth-object",
            auth_key=auth_key,
            xr_namespace=xr_namespace,
            qdrant_auth_secret=qdrant_auth_secret,
        )
        rsp.desired.resources[auth_key].resource.update(auth_body)

        persistence = {"size": qdrant_storage}
        if qdrant_storage_class:
            persistence["storageClassName"] = qdrant_storage_class

        qdrant = _render_template(
            req,
            "qdrant/store",
            store_name=store_name,
            workshop_ns=workshop_ns,
            qdrant_auth_secret_name=qdrant_auth_secret_name,
            persistence=persistence,
        )

        key = f"qdrant-vector-{xr_name}-{store_name}"
        body = _render_template(
            req,
            "qdrant/store-object",
            key=key,
            xr_namespace=xr_namespace,
            qdrant=qdrant,
        )
        rsp.desired.resources[key].resource.update(body)

        pod_key = f"qdrant-pod-{xr_name}-{store_name}"
        pod_body = _render_template(
            req,
            "qdrant/pod-observer",
            pod_key=pod_key,
            xr_namespace=xr_namespace,
            pod_name=f"qdrant-{store_name}-0",
            workshop_ns=workshop_ns,
        )
        rsp.desired.resources[pod_key].resource.update(pod_body)
