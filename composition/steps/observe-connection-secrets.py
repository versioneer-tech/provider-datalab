# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

from crossplane.function.proto.v1 import run_function_pb2 as fnv1

from composition.helpers import (
    _boolish,
    _to_dict,
)
from composition.render import _render_template


def compose(req: fnv1.RunFunctionRequest, rsp: fnv1.RunFunctionResponse):
    xr = _to_dict(req.observed.composite.resource)
    metadata = xr.get("metadata", {}) or {}
    spec = xr.get("spec", {}) or {}
    xr_name = metadata.get("name")
    xr_namespace = metadata.get("namespace") or "default"

    context = _to_dict(req.context)
    environment = context.get("apiextensions.crossplane.io/environment", {}) or {}
    runtime_namespace = xr_name

    def observe(key, secret_name, secret_namespace):
        rsp.desired.resources[key].resource.update(
            _render_template(
                req,
                "secrets/observer",
                key=key,
                xr_namespace=xr_namespace,
                secret_name=secret_name,
                secret_namespace=secret_namespace,
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
    )

    postgres_clusters = spec.get("databases")
    if isinstance(postgres_clusters, dict):
        for name in sorted(postgres_clusters):
            if isinstance(name, str) and name.strip():
                cluster_name = name.strip()
                observe(
                    f"observe-database-secret-{xr_name}-{cluster_name}",
                    f"{cluster_name}-pguser-postgres",
                    runtime_namespace,
                )

    for field, backend in (
        ("documentStores", "mongodb"),
        ("cacheStores", "redis"),
    ):
        stores = spec.get(field) or {}
        if isinstance(stores, dict):
            for name in sorted(stores):
                if isinstance(name, str) and name.strip():
                    store_name = name.strip()
                    observe(
                        f"observe-{backend}-auth-secret-{xr_name}-{store_name}",
                        f"{store_name}-{backend}-auth",
                        runtime_namespace,
                    )

    data_config = (environment.get("defaults") or {}).get("data") or {}
    data_enabled = data_config.get("enabled")
    if data_enabled is None:
        data_enabled = True
    if _boolish(data_enabled) and runtime_namespace:
        observe(
            f"observe-runtime-storage-secret-{xr_name}",
            f"{xr_name}-storage",
            runtime_namespace,
        )
