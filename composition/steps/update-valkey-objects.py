# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

import base64
import hashlib

from crossplane.function.proto.v1 import run_function_pb2 as fnv1
from crossplane.function import response

from composition.helpers import (
    _extract_manifest,
    _name_hash,
    _resource_name,
    _safe_str,
    _service_token,
    _store_resource_name,
    _stores,
    _to_dict,
)
from composition.render import _render_template


BACKUP_SCRIPT = _embedded_script("scripts/valkey-snapshot.py")
SNAPSHOT_SCRIPT = _embedded_script("scripts/volume-snapshot.py")


def compose(req: fnv1.RunFunctionRequest, rsp: fnv1.RunFunctionResponse):
    xr = _to_dict(req.observed.composite.resource)
    metadata = xr.get("metadata", {}) or {}
    spec = xr.get("spec", {}) or {}

    xr_name = metadata.get("name")
    xr_namespace = metadata.get("namespace") or "default"

    cache_stores = _stores(spec, "valkey")
    if not isinstance(cache_stores, dict) or not cache_stores:
        return

    context = _to_dict(req.context)
    environment = context.get("apiextensions.crossplane.io/environment", {}) or {}
    images = environment.get("images") or {}
    valkey_image = _safe_str(images.get("valkey")) or "valkey/valkey:9.2.0-alpine@sha256:c8e2d17498838af5d91e12eb7c11220b3434a7b7131a333e3af52ad5e0b80882"
    backup_image = _safe_str(images.get("volumeSnapshot")) or "python:3.13-alpine@sha256:9ef1a599f863231c3d91e941389bfdc4a2d6070557243d54df1a4e57015b960e"
    valkey_env = environment.get("cacheStore") or {}
    valkey_storage_class = _safe_str(valkey_env.get("storageClassName") or "")

    runtime_namespace = xr_name

    for store_key in sorted(list(cache_stores.keys())):
        if not isinstance(store_key, str) or not store_key.strip():
            continue
        store_cfg = cache_stores.get(store_key) or {}
        if not isinstance(store_cfg, dict):
            continue

        valkey_storage = _safe_str(store_cfg.get("storage") or "1Gi")
        if not valkey_storage:
            continue
        store_name = store_key.strip()
        backups_enabled = store_cfg.get("backups") is True
        server_name = _store_resource_name("valkey", store_name)
        valkey_auth_secret_name = server_name + "-auth"
        valkey_password = _service_token(
            req, rsp, f"valkey-auth-{xr_name}-{store_name}",
            valkey_auth_secret_name, runtime_namespace,
            old=_name_hash(f"{xr_name}:{store_name}:valkey", suffix="", length=28),
        )
        valkey_auth_secret = _render_template(
            req,
            "valkey/auth-secret",
            valkey_auth_secret_name=valkey_auth_secret_name,
            runtime_namespace=runtime_namespace,
            valkey_user="default",
            valkey_password=valkey_password,
        )
        auth_key = f"valkey-auth-secret-{xr_name}-{store_name}"
        auth_body = _render_template(
            req,
            "valkey/auth-object",
            auth_key=auth_key,
            xr_namespace=xr_namespace,
            valkey_auth_secret=valkey_auth_secret,
        )
        rsp.desired.resources[auth_key].resource.update(auth_body)

        valkey_acl_secret_name = server_name + "-acl"
        acl = f"user default on >{valkey_password} ~* +@all\n"
        if backups_enabled:
            backup_password = _service_token(
                req, rsp, f"valkey-backup-auth-{xr_name}-{store_name}",
                server_name + "-backup-auth", runtime_namespace,
                old=_name_hash(f"{xr_name}:{store_name}:valkey:backup"),
            )
            acl += f"user backup on >{backup_password} -@all +ping +info +bgsave +client|pause +client|unpause\n"
        encoded_acl = base64.b64encode(acl.encode()).decode()
        valkey_acl_secret = _render_template(
            req,
            "valkey/acl-secret",
            valkey_acl_secret_name=valkey_acl_secret_name,
            runtime_namespace=runtime_namespace,
            data_user_acl=encoded_acl,
        )
        acl_key = f"valkey-acl-secret-{xr_name}-{store_name}"
        acl_body = _render_template(
            req,
            "valkey/acl-object",
            acl_key=acl_key,
            xr_namespace=xr_namespace,
            valkey_acl_secret=valkey_acl_secret,
        )
        rsp.desired.resources[acl_key].resource.update(acl_body)
        acl_checksum = hashlib.sha256(encoded_acl.encode()).hexdigest()

        pvc_spec = {
            "accessModes": ["ReadWriteOnce"],
            "resources": {"requests": {"storage": valkey_storage}},
        }
        if valkey_storage_class:
            pvc_spec["storageClassName"] = valkey_storage_class
        pvc_name = _resource_name("valkey", store_name, "data")
        pvc_key = f"valkey-data-{xr_name}-{store_name}"
        rsp.desired.resources[pvc_key].resource.update(_render_template(
            req, "common/object", key=pvc_key, xr_namespace=xr_namespace,
            manifest={"apiVersion": "v1", "kind": "PersistentVolumeClaim",
                      "metadata": {"name": pvc_name, "namespace": runtime_namespace}, "spec": pvc_spec},
            readiness={"policy": "DeriveFromCelQuery", "celQuery":
                       "has(object.status) && has(object.status.phase) && object.status.phase == 'Bound'"},
        ))

        service_key = f"valkey-service-{xr_name}-{store_name}"
        rsp.desired.resources[service_key].resource.update(_render_template(
            req, "common/object", key=service_key, xr_namespace=xr_namespace,
            manifest={"apiVersion": "v1", "kind": "Service",
                      "metadata": {"name": server_name, "namespace": runtime_namespace},
                      "spec": {"selector": {"app.kubernetes.io/name": "valkey",
                                            "app.kubernetes.io/instance": store_name},
                               "ports": [{"name": "valkey", "port": 6379, "targetPort": "valkey"}]}},
            readiness={"policy": "SuccessfulCreate"},
        ))
        valkey_manifest = _render_template(
            req,
            "valkey/store",
            valkey_image=valkey_image,
            store_name=store_name, workload_name=server_name,
            runtime_namespace=runtime_namespace,
            valkey_auth_secret_name=valkey_auth_secret_name,
            valkey_acl_secret_name=valkey_acl_secret_name,
            valkey_acl_checksum=acl_checksum,
            pvc_name=pvc_name,
        )

        key = f"valkey-cache-{xr_name}-{store_name}"
        body = _render_template(
            req,
            "valkey/store-object",
            key=key,
            xr_namespace=xr_namespace,
            valkey_manifest=valkey_manifest,
        )
        rsp.desired.resources[key].resource.update(body)

        if backups_enabled:
            backup_name = server_name + "-backup"
            backup_secret_name = server_name + "-backup-auth"
            backup_secret = _render_template(
                req,
                "valkey/auth-secret",
                valkey_auth_secret_name=backup_secret_name,
                runtime_namespace=runtime_namespace,
                valkey_user="backup",
                valkey_password=backup_password,
            )
            snapshot_class = valkey_env.get("snapshotClassName") or (environment.get("volumes") or {}).get("snapshotClassName")
            retention = valkey_env.get("maxSnapshots", 4)
            if not isinstance(snapshot_class, str) or not snapshot_class.strip():
                response.fatal(rsp, "Valkey backups require data.cacheStore.snapshotClassName or data.volumes.snapshotClassName.")
                return
            if (isinstance(retention, bool) or not isinstance(retention, (int, float))
                    or retention != int(retention) or not 1 <= retention <= 100):
                response.fatal(rsp, "data.cacheStore.maxSnapshots must be an integer from 1 to 100.")
                return
            pod = _extract_manifest(req.observed.resources.get(f"valkey-pod-{xr_name}-{store_name}"))
            volumes = {v["name"]: v.get("persistentVolumeClaim", {}).get("claimName")
                       for v in (pod.get("spec") or {}).get("volumes", [])}
            claims = {volumes.get(m["name"]) for c in (pod.get("spec") or {}).get("containers", [])
                      for m in c.get("volumeMounts", []) if m["mountPath"] == "/data"}
            claim = next(iter(claims)) if len(claims) == 1 and None not in claims else "unbound"
            resources = _render_template(
                req, "valkey/backup-cronjob", target=runtime_namespace, pvc_name=claim,
                volume_name=store_name, backup_name=backup_name,
                backup_binding=_resource_name(runtime_namespace, backup_name),
                snapshot_class=snapshot_class, max_snapshots=str(int(retention)),
                schedule=valkey_env.get("schedule") or "0 1 * * *",
                backup_script=BACKUP_SCRIPT, snapshot_script=SNAPSHOT_SCRIPT,
                backup_image=backup_image, backup_secret_name=backup_secret_name,
                pod_name=server_name + "-0", server_name=server_name, suspended=claim == "unbound",
            )["resources"]
            resources["auth-secret"] = backup_secret
            resources["class"] = {
                "apiVersion": "snapshot.storage.k8s.io/v1", "kind": "VolumeSnapshotClass",
                "metadata": {"name": snapshot_class},
            }
            for resource_type, manifest in resources.items():
                backup_key = f"valkey-backup-{resource_type}-{xr_name}-{store_name}"
                readiness = ({"policy": "DeriveFromCelQuery", "celQuery": "object.deletionPolicy == 'Delete'"}
                             if resource_type == "class" else {"policy": "SuccessfulCreate"})
                backup_body = _render_template(
                    req, "common/object", key=backup_key, xr_namespace=xr_namespace,
                    manifest=manifest, readiness=readiness,
                )
                if resource_type == "class":
                    backup_body["spec"]["managementPolicies"] = ["Observe"]
                rsp.desired.resources[backup_key].resource.update(backup_body)

        pod_key = f"valkey-pod-{xr_name}-{store_name}"
        pod_body = _render_template(
            req,
            "common/pod-observer",
            pod_key=pod_key,
            xr_namespace=xr_namespace,
            pod_name=server_name + "-0",
            runtime_namespace=runtime_namespace,
        )
        rsp.desired.resources[pod_key].resource.update(pod_body)
