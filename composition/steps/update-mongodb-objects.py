# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

import re

from crossplane.function.proto.v1 import run_function_pb2 as fnv1

from composition.helpers import (
    _backup_enabled,
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

    document_stores = spec.get("documentStores")
    if not isinstance(document_stores, dict) or not document_stores:
        return

    context = _to_dict(req.context)
    environment = context.get("apiextensions.crossplane.io/environment", {}) or {}
    mongo_env = environment.get("documentStore") or {}
    images = environment.get("images") or {}
    mongo_image = _safe_str(images.get("mongo"))
    version_tag = re.search(r":(\d+\.\d+\.\d+)(?:-[^@]+)?(?:@.*)?$", mongo_image)
    mongo_version = _safe_str(mongo_env.get("version")) or (version_tag[1] if version_tag else "8.0.12")
    mongo_image = mongo_image or f"quay.io/mongodb/mongodb-community-server:{mongo_version}-ubi8"
    backup_image = _safe_str(images.get("mongoBackup")) or f"mongo:{mongo_version}"
    mongo_storage_class = _string_value(mongo_env.get("storageClassName") or "")
    backup_storage_class = _string_value(mongo_env.get("backupStorageClassName") or "")

    runtime_namespace = xr_name

    # MongoDB operator expects these namespace-local prerequisites.
    prereqs = [
        (
            f"mongodb-sa-appdb-{xr_name}",
            _render_template(
                req,
                "mongodb/serviceaccount-mongodb-kubernetes-appdb",
                runtime_namespace=runtime_namespace,
            ),
        ),
        (
            f"mongodb-sa-database-pods-{xr_name}",
            _render_template(
                req,
                "mongodb/serviceaccount-mongodb-kubernetes-database-pods",
                runtime_namespace=runtime_namespace,
            ),
        ),
        (
            f"mongodb-sa-ops-manager-{xr_name}",
            _render_template(
                req,
                "mongodb/serviceaccount-mongodb-kubernetes-ops-manager",
                runtime_namespace=runtime_namespace,
            ),
        ),
        (
            f"mongodb-role-appdb-{xr_name}",
            _render_template(
                req,
                "mongodb/role-mongodb-kubernetes-appdb",
                runtime_namespace=runtime_namespace,
            ),
        ),
        (
            f"mongodb-rb-appdb-{xr_name}",
            _render_template(
                req,
                "mongodb/rolebinding-mongodb-kubernetes-appdb",
                runtime_namespace=runtime_namespace,
            ),
        ),
    ]
    for key, manifest in prereqs:
        body = _render_template(
            req,
            "common/object",
            key=key,
            xr_namespace=xr_namespace,
            manifest=manifest,
            readiness={"policy": "SuccessfulCreate"},
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
        app_username = f"{store_name}-app"
        mongo_password = _strong_token(f"{xr_name}:{store_name}:mongodb")
        password_secret = _render_template(
            req,
            "mongodb/auth-secret",
            password_secret_name=password_secret_name,
            runtime_namespace=runtime_namespace,
            app_username=app_username,
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
            mongo_version=mongo_version,
            mongo_image=mongo_image,
            mongo_resource_name=mongo_resource_name,
            runtime_namespace=runtime_namespace,
            app_username=app_username,
            password_secret_name=password_secret_name,
            store_name=store_name,
            scram_secret_name=f"{store_name}-app-scram",
            pvc_spec=pvc_spec,
        )
        backup_storage = _string_value(store_cfg.get("backupStorage") or "0")
        if _backup_enabled(backup_storage):
            backup_name = f"{mongo_resource_name}-backup"
            backup_secret_name = f"{store_name}-mongodb-backup-auth"
            backup_username = f"{store_name}-backup"
            backup_password = _strong_token(f"{xr_name}:{store_name}:mongodb:backup")
            backup_secret = _render_template(
                req,
                "mongodb/backup-secret",
                backup_secret_name=backup_secret_name,
                runtime_namespace=runtime_namespace,
                backup_password=backup_password,
                backup_config=f"password: {backup_password}\n",
            )
            backup_vcs = {
                "accessModes": ["ReadWriteOnce"],
                "resources": {"requests": {"storage": backup_storage}},
            }
            if backup_storage_class:
                backup_vcs["storageClassName"] = backup_storage_class
            backup_pvc = _render_template(
                req,
                "mongodb/backup-pvc",
                backup_name=backup_name,
                runtime_namespace=runtime_namespace,
                backup_vcs=backup_vcs,
            )
            backup_job = _render_template(
                req,
                "mongodb/backup-cronjob",
                backup_name=backup_name,
                runtime_namespace=runtime_namespace,
                backup_secret_name=backup_secret_name,
                backup_username=backup_username,
                backup_host=f"{mongo_resource_name}/{mongo_resource_name}-0.{mongo_resource_name}-svc:27017",
                mongo_image=backup_image,
            )
            mongo["spec"]["users"].append(
                {
                    "name": backup_username,
                    "db": "admin",
                    "passwordSecretRef": {"name": backup_secret_name, "key": "password"},
                    "roles": [{"name": "backup", "db": "admin"}],
                    "scramCredentialsSecretName": f"{store_name}-backup-scram",
                }
            )
            for resource_type, manifest in (
                ("auth-secret", backup_secret),
                ("pvc", backup_pvc),
                ("cronjob", backup_job),
            ):
                backup_key = f"mongodb-backup-{resource_type}-{xr_name}-{store_name}"
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

        key = f"mongodb-community-{xr_name}-{store_name}"
        body = _render_template(
            req,
            "mongodb/store-object",
            key=key,
            xr_namespace=xr_namespace,
            mongo=mongo,
        )
        rsp.desired.resources[key].resource.update(body)
