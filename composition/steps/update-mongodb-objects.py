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

    document_stores = spec.get("documentStores")
    if not isinstance(document_stores, dict) or not document_stores:
        return

    context = _to_dict(req.context)
    environment = context.get("apiextensions.crossplane.io/environment", {}) or {}
    mongo_env = environment.get("documentStore") or {}
    mongo_storage_class = _string_value(mongo_env.get("storageClassName") or "")

    observed = getattr(req.observed, "resources", None) or {}
    env_key = f"workshopenvironment-{xr_name}"
    environment_manifest = _extract_manifest(observed.get(env_key))

    educates_status = (environment_manifest.get("status") or {}).get("educates") or {}
    workshop_namespace = _string_value(educates_status.get("namespace") or xr_name)

    if not workshop_namespace:
        return

    # MongoDB operator expects these namespace-local prerequisites.
    prereqs = [
        (
            f"mongodb-sa-appdb-{xr_name}",
            _render_template(
                req,
                "mongodb/serviceaccount-mongodb-kubernetes-appdb",
                workshop_ns=workshop_namespace,
            ),
        ),
        (
            f"mongodb-sa-database-pods-{xr_name}",
            _render_template(
                req,
                "mongodb/serviceaccount-mongodb-kubernetes-database-pods",
                workshop_ns=workshop_namespace,
            ),
        ),
        (
            f"mongodb-sa-ops-manager-{xr_name}",
            _render_template(
                req,
                "mongodb/serviceaccount-mongodb-kubernetes-ops-manager",
                workshop_ns=workshop_namespace,
            ),
        ),
        (
            f"mongodb-role-appdb-{xr_name}",
            _render_template(
                req,
                "mongodb/role-mongodb-kubernetes-appdb",
                workshop_ns=workshop_namespace,
            ),
        ),
        (
            f"mongodb-rb-appdb-{xr_name}",
            _render_template(
                req,
                "mongodb/rolebinding-mongodb-kubernetes-appdb",
                workshop_ns=workshop_namespace,
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

        mongo_storage = _string_value(store_cfg.get("storage") or "10Gi")
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
            workshop_ns=workshop_namespace,
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
            workshop_ns=workshop_namespace,
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
