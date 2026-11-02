# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

from crossplane.function.proto.v1 import run_function_pb2 as fnv1
from google.protobuf import json_format


def _to_dict(struct):
    return (
        {}
        if struct is None
        else json_format.MessageToDict(struct, preserving_proto_field_name=True)
    )


def _boolish(value):
    if isinstance(value, bool):
        return value
    return str(value).lower() in ("true", "1", "yes", "on")


def _safe_str(value):
    return str(value).strip() if value is not None else ""


def _extract_manifest(objres):
    if not objres or not getattr(objres, "resource", None):
        return {}
    obj = _to_dict(objres.resource)
    at_provider = (obj.get("status") or {}).get("atProvider") or {}
    return (
        at_provider.get("manifest")
        or (at_provider.get("raw") or {}).get("manifest")
        or {}
    ) or {}


def compose(req: fnv1.RunFunctionRequest, rsp: fnv1.RunFunctionResponse):
    xr = _to_dict(req.observed.composite.resource)
    metadata = xr.get("metadata", {}) or {}
    spec = xr.get("spec", {}) or {}
    xr_name = metadata.get("name")
    xr_namespace = metadata.get("namespace") or "default"

    context = _to_dict(req.context)
    environment = context.get("apiextensions.crossplane.io/environment", {}) or {}
    observed = getattr(req.observed, "resources", {}) or {}
    environment_manifest = _extract_manifest(
        observed.get(f"workshopenvironment-{xr_name}")
    )
    educates_status = (environment_manifest.get("status") or {}).get("educates") or {}
    workshop_namespace = _safe_str(educates_status.get("namespace") or xr_name)

    def observe(key, secret_name, secret_namespace, watch=True):
        rsp.desired.resources[key].resource.update(
            _render_template(
                req,
                "secrets/observer",
                key=key,
                xr_namespace=xr_namespace,
                secret_name=secret_name,
                secret_namespace=secret_namespace,
                watch=watch,
            )
        )

    storage_config = environment.get("storage") or {}
    observe(
        f"observe-storage-secret-{xr_name}",
        spec.get("secretName") or xr_name,
        storage_config.get("secretNamespace") or xr_namespace,
    )
    observe(
        f"observe-oauth-client-secret-{xr_name}",
        f"{xr_name}-oauth-client",
        xr_namespace,
        watch=False,
    )

    postgres_clusters = spec.get("databases")
    if isinstance(postgres_clusters, dict):
        for name in sorted(postgres_clusters):
            if isinstance(name, str) and name.strip():
                cluster_name = name.strip()
                observe(
                    f"observe-database-secret-{xr_name}-{cluster_name}",
                    f"{cluster_name}-pguser-postgres",
                    xr_name,
                )

    for field, backend in (
        ("documentStores", "mongodb"),
        ("cacheStores", "redis"),
        ("vectorStores", "qdrant"),
    ):
        stores = spec.get(field) or {}
        if isinstance(stores, dict):
            for name in sorted(stores):
                if isinstance(name, str) and name.strip():
                    store_name = name.strip()
                    observe(
                        f"observe-{backend}-auth-secret-{xr_name}-{store_name}",
                        f"{store_name}-{backend}-auth",
                        workshop_namespace,
                    )

    data_config = (environment.get("defaults") or {}).get("data") or {}
    data_enabled = data_config.get("enabled")
    if data_enabled is None:
        data_enabled = True
    runtime_namespace = _safe_str(educates_status.get("namespace"))
    if _boolish(data_enabled) and runtime_namespace:
        observe(
            f"observe-runtime-storage-secret-{xr_name}",
            f"{xr_name}-datalab",
            runtime_namespace,
        )
