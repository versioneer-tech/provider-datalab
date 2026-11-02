# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

from crossplane.function.proto.v1 import run_function_pb2 as fnv1
from google.protobuf import json_format as _json_format


def _to_dict(struct):
    return (
        {}
        if struct is None
        else _json_format.MessageToDict(struct, preserving_proto_field_name=True)
    )


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

    document_stores = spec.get("documentStores")
    if not isinstance(document_stores, dict) or not document_stores:
        return

    ctx = _to_dict(req.context)
    env = ctx.get("apiextensions.crossplane.io/environment", {}) or {}
    mongo_env = env.get("documentStore") or {}
    mongo_storage_class = _safe_str(mongo_env.get("storageClassName") or "")

    observed = getattr(req.observed, "resources", None) or {}
    env_key = f"workshopenvironment-{xr_name}"
    env_manifest = _extract_manifest(observed.get(env_key))

    educates_status = (env_manifest.get("status") or {}).get("educates") or {}
    workshop_ns = _safe_str(educates_status.get("namespace") or xr_name)

    if not workshop_ns:
        return

    # MongoDB operator expects these namespace-local prerequisites.
    prereqs = [
        (
            f"mongodb-sa-appdb-{xr_name}",
            _render_template(
                req,
                "mongodb/serviceaccount-mongodb-kubernetes-appdb",
                workshop_ns=workshop_ns,
            ),
        ),
        (
            f"mongodb-sa-database-pods-{xr_name}",
            _render_template(
                req,
                "mongodb/serviceaccount-mongodb-kubernetes-database-pods",
                workshop_ns=workshop_ns,
            ),
        ),
        (
            f"mongodb-sa-ops-manager-{xr_name}",
            _render_template(
                req,
                "mongodb/serviceaccount-mongodb-kubernetes-ops-manager",
                workshop_ns=workshop_ns,
            ),
        ),
        (
            f"mongodb-role-appdb-{xr_name}",
            _render_template(
                req,
                "mongodb/role-mongodb-kubernetes-appdb",
                workshop_ns=workshop_ns,
            ),
        ),
        (
            f"mongodb-rb-appdb-{xr_name}",
            _render_template(
                req,
                "mongodb/rolebinding-mongodb-kubernetes-appdb",
                workshop_ns=workshop_ns,
            ),
        ),
    ]
    for key, manifest in prereqs:
        body = _render_template(
            req,
            "mongodb/rbac-object",
            key=key,
            xr_namespace=xr_namespace,
            manifest=manifest,
        )
        rsp.desired.resources[key].resource.update(body)

    for store_key in sorted(list(document_stores.keys())):
        if not isinstance(store_key, str) or not store_key.strip():
            continue
        store_cfg = document_stores.get(store_key) or {}
        if not isinstance(store_cfg, dict):
            continue

        mongo_storage = _safe_str(store_cfg.get("storage") or "10Gi")
        if not mongo_storage:
            continue
        pvc_spec = {
            "accessModes": ["ReadWriteOnce"],
            "resources": {"requests": {"storage": mongo_storage}},
        }
        if mongo_storage_class:
            pvc_spec["storageClassName"] = mongo_storage_class

        store_name = store_key.strip()
        mongo_resource_name = f"mongodb-{store_name}"
        password_secret_name = f"{store_name}-mongodb-auth"
        mongo_password = _strong_token(f"{xr_name}:{store_name}:mongodb")
        password_secret = _render_template(
            req,
            "mongodb/auth-secret",
            password_secret_name=password_secret_name,
            workshop_ns=workshop_ns,
            mongo_password=mongo_password,
        )
        pwd_key = f"mongodb-auth-secret-{xr_name}-{store_name}"
        pwd_body = _render_template(
            req,
            "mongodb/auth-object",
            pwd_key=pwd_key,
            xr_namespace=xr_namespace,
            password_secret=password_secret,
        )
        rsp.desired.resources[pwd_key].resource.update(pwd_body)

        mongo = _render_template(
            req,
            "mongodb/store",
            mongo_resource_name=mongo_resource_name,
            workshop_ns=workshop_ns,
            app_username=f"{store_name}-app",
            password_secret_name=password_secret_name,
            store_name=store_name,
            scram_secret_name=f"{store_name}-app-scram",
            pvc_spec=pvc_spec,
        )

        key = f"mongodb-community-{xr_name}-{store_name}"
        body = _render_template(
            req,
            "mongodb/store-object",
            key=key,
            xr_namespace=xr_namespace,
            mongo=mongo,
        )
        rsp.desired.resources[key].resource.update(body)
