# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

import base64
from collections import Counter

from crossplane.function.proto.v1 import run_function_pb2 as fnv1

from composition.helpers import (
    _b64get_any,
    _boolish,
    _extract_data,
    _extract_manifest,
    _resource_name,
    _safe_str,
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
    observed = getattr(req.observed, "resources", {}) or {}
    environment_manifest = _extract_manifest(
        observed.get(f"workshopenvironment-{xr_name}")
    )
    educates_status = (environment_manifest.get("status") or {}).get("educates") or {}
    runtime_namespace = _safe_str(educates_status.get("namespace"))
    workshop_namespace = _safe_str(educates_status.get("namespace") or xr_name)
    status = _to_dict(rsp.desired.composite.resource).get("status") or xr.get("status") or {}
    connections = []

    def observe(key, secret_name, secret_namespace, kind=None, instance=None):
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
        if kind == "custom":
            rsp.desired.resources[key].ready = fnv1.READY_TRUE
        if kind and (kind in ("s3", "custom") or educates_status.get("namespace")):
            source = observed.get(key)
            body = _to_dict(source.resource) if source else {}
            conditions = (body.get("status") or {}).get("conditions") or []
            source_meta = _extract_manifest(source).get("metadata") or {}
            present = (
                source_meta.get("name") == secret_name
                and source_meta.get("namespace") == secret_namespace
                and not source_meta.get("deletionTimestamp")
                and not body.get("metadata", {}).get("deletionTimestamp")
            )
            if kind == "s3" and not present:
                return
            connection = {
                "name": instance,
                "type": kind,
                "secretRef": {"name": secret_name, "namespace": secret_namespace},
                "ready": (
                    present
                    and any(c.get("type") == "Ready" and c.get("status") == "True" for c in conditions)
                    and not any(c.get("type") == "Synced" and c.get("status") == "False" for c in conditions)
                ),
            }
            if kind in ("postgres", "mongo", "redis", "registry", "custom"):
                connection = publish_connection(connection, source, present)
                if kind == "custom" and connection is None:
                    return
            if kind == "s3":
                data = _extract_data(source)
                for field, secret_key in (
                    ("endpoint", "AWS_ENDPOINT_URL"),
                    ("region", "AWS_REGION"),
                ):
                    value = _b64get_any(data, [secret_key]) or storage_config.get(field)
                    if value:
                        connection[field] = value
            if kind == "registry":
                ingress, gateway = environment.get("ingress") or {}, environment.get("httpRoute") or {}
                public = _boolish(ingress.get("enabled")) or _boolish(gateway.get("enabled"))
                connection["endpoint"] = (
                    f"https://{xr_name}.{ingress.get('domain', 'default')}/v2/" if public
                    else f"http://registry.{workshop_namespace}.svc:5000/v2/"
                )
                keys = [f"registry-deployment-{xr_name}"]
                if _boolish(gateway.get("enabled")):
                    keys.append(f"registry-route-{xr_name}")
                elif public:
                    keys.append(f"registry-ingress-{xr_name}")
                connection["ready"] = connection["ready"] and all(
                    source_ready(_to_dict(observed[key].resource)) if key in observed else False
                    for key in keys
                )
            connections.append(connection)

    def publish_connection(connection, source, present):
        kind, instance = connection["type"], connection["name"]
        secret_name = _resource_name(xr_name, kind, instance, "connection")
        key = _resource_name("connection", secret_name)
        source_manifest = _extract_manifest(source)
        data = dict(source_manifest.get("data") or {})
        data.update({name: base64.b64encode(value.encode()).decode()
                     for name, value in (source_manifest.get("stringData") or {}).items()})
        required = {
            "postgres": ("host", "port", "user", "password", "dbname", "uri"),
            "mongo": ("user", "password"),
            "redis": ("user", "password"),
            "registry": ("user", "password"),
        }.get(kind, ())
        if kind != "custom":
            data = {name: value for name, value in data.items() if name in required}
        available = (present and connection["ready"] and bool(data)
                     and all(data.get(name) for name in required))
        if kind == "custom" and not available:
            return None
        connection["secretRef"] = {"name": secret_name, "namespace": xr_namespace}
        connection["ready"] = False
        if available:
            secret_type = (source_manifest.get("type") or "Opaque") if kind == "custom" else "Opaque"
            # Token copies must not attach to another namespace's account controller.
            if secret_type in ("kubernetes.io/service-account-token", "bootstrap.kubernetes.io/token"):
                secret_type = "Opaque"
            secret = _render_template(
                req, "secrets/connection", key=key, name=xr_name,
                namespace=xr_namespace, secret_name=secret_name,
                connection_name=_resource_name(kind, instance), values=data,
            )
            secret["type"] = secret_type
            rsp.desired.resources[key].resource.update(secret)
            published = observed.get(key)
            body = _to_dict(published.resource) if published else {}
            # Native Secrets have no Ready condition. Compare their actual data.
            connection["ready"] = (
                body.get("apiVersion") == "v1" and body.get("kind") == "Secret"
                and body.get("metadata", {}).get("name") == secret_name
                and body.get("metadata", {}).get("namespace") == xr_namespace
                and not body.get("metadata", {}).get("deletionTimestamp")
                and body.get("type") == secret_type and body.get("data") == data
            )
            rsp.desired.resources[key].ready = (
                fnv1.READY_TRUE if connection["ready"] else fnv1.READY_FALSE
            )
        return connection

    storage_config = environment.get("storage") or {}
    observe(
        f"observe-storage-secret-{xr_name}",
        xr_name,
        storage_config.get("secretNamespace") or xr_namespace,
        kind="s3",
        instance="primary",
    )
    observe(
        f"observe-oauth-client-secret-{xr_name}",
        f"{xr_name}-oauth-client",
        xr_namespace,
    )
    status["oauth2"] = []
    client = observed.get(f"keycloak-client-{xr_name}")
    client_body = _to_dict(client.resource) if client else {}
    oauth_source = observed.get(f"observe-oauth-client-secret-{xr_name}")
    oauth_body = _to_dict(oauth_source.resource) if oauth_source else {}
    oauth_meta = _extract_manifest(oauth_source).get("metadata") or {}
    oauth_data = _extract_data(oauth_source)
    credential_id = _b64get_any(oauth_data, ["clientID", "client_id", "attribute.client_id"])
    client_id = _safe_str(
        (client_body.get("status", {}).get("atProvider") or {}).get("clientId")
        or (client_body.get("spec", {}).get("forProvider") or {}).get("clientId")
        or credential_id
    )
    issuer = _safe_str((environment.get("iam") or {}).get("issuerURL")).rstrip("/")
    # A missing Secret can leave its last manifest in the observer status.
    source_missing = any(
        c.get("type") == "Synced" and c.get("status") == "False"
        and "external resource does not exist" in c.get("message", "")
        for c in (oauth_body.get("status") or {}).get("conditions") or []
    )

    def source_ready(body):
        conditions = (body.get("status") or {}).get("conditions") or []
        return (
            any(c.get("type") == "Ready" and c.get("status") == "True" for c in conditions)
            and not any(c.get("type") == "Synced" and c.get("status") == "False" for c in conditions)
        )

    if (
        client_body and client_id and issuer
        and not client_body.get("metadata", {}).get("deletionTimestamp")
        and oauth_meta.get("name") == f"{xr_name}-oauth-client"
        and oauth_meta.get("namespace") == xr_namespace
        and not oauth_meta.get("deletionTimestamp")
        and not oauth_body.get("metadata", {}).get("deletionTimestamp")
        and not source_missing
    ):
        status["oauth2"].append({
            "name": client_id,
            "type": "client",
            "issuerUrl": issuer,
            "secretRef": {"name": f"{xr_name}-oauth-client", "namespace": xr_namespace},
            "ready": bool(
                source_ready(client_body) and source_ready(oauth_body)
                and _b64get_any(oauth_data, ["clientSecret", "client_secret"])
                and (not credential_id or credential_id == client_id)
            ),
        })

    custom_secrets = environment.get("customSecrets") or []
    custom_names = Counter(custom["name"] for custom in custom_secrets)
    for custom in custom_secrets:
        secret_name = custom["name"]
        secret_namespace = custom.get("namespace") or runtime_namespace
        if not secret_namespace or custom_names[secret_name] != 1:
            continue
        observe(
            _resource_name("observe-custom-secret", xr_name, secret_namespace, secret_name),
            secret_name,
            secret_namespace,
            kind="custom",
            instance=secret_name,
        )

    postgres_clusters = spec.get("databases")
    if isinstance(postgres_clusters, dict):
        for name in sorted(postgres_clusters):
            if isinstance(name, str) and name.strip():
                cluster_name = name.strip()
                observe(
                    f"observe-database-secret-{xr_name}-{cluster_name}",
                    f"{cluster_name}-pguser-postgres",
                    workshop_namespace,
                    kind="postgres",
                    instance=cluster_name,
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
                        workshop_namespace,
                        kind="mongo" if backend == "mongodb" else "redis",
                        instance=store_name,
                    )

    registry_enabled = _boolish(((environment.get("defaults") or {}).get("registry") or {}).get("enabled", True))
    if registry_enabled:
        observe(f"observe-registry-auth-secret-{xr_name}", "registry-auth", workshop_namespace,
                kind="registry", instance="primary")

    data_config = (environment.get("defaults") or {}).get("data") or {}
    data_enabled = data_config.get("enabled")
    if data_enabled is None:
        data_enabled = True
    if (_boolish(data_enabled) or registry_enabled) and runtime_namespace:
        observe(
            f"observe-runtime-storage-secret-{xr_name}",
            f"{xr_name}-datalab",
            runtime_namespace,
        )
    status["connections"] = connections + [
        item for item in status.get("connections", []) if item.get("type") == "vcluster"
    ]
    rsp.desired.composite.resource.update({"status": status})
