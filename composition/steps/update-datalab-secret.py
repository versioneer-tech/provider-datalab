# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

import base64 as _base64
from crossplane.function.proto.v1 import run_function_pb2 as fnv1
from google.protobuf import json_format as _json_format
import re
from urllib.parse import urlsplit, urlunsplit


def _to_dict(s):
    if s is None:
        return {}
    return (
        s
        if isinstance(s, dict)
        else _json_format.MessageToDict(s, preserving_proto_field_name=True)
    )


def _safe_str(v):
    return str(v).strip()


def _b64get_any(d, keys):
    if not d:
        return None
    for k in keys:
        v = d.get(k)
        if v is None:
            continue
        try:
            return _base64.b64decode(v, validate=True).decode("utf-8")
        except Exception:
            return str(v)
    return None


def _extract_data(objres):
    if not objres or not getattr(objres, "resource", None):
        return {}
    od = _to_dict(objres.resource)
    st = (od.get("status") or {}).get("atProvider") or {}
    m1 = st.get("manifest") or {}
    m2 = (st.get("raw") or {}).get("manifest") or {}
    return (
        m1.get("data")
        or m1.get("stringData")
        or m2.get("data")
        or m2.get("stringData")
        or {}
    ) or {}


def _extract_manifest(objres):
    if not objres or not getattr(objres, "resource", None):
        return {}
    od = _to_dict(objres.resource)
    st = (od.get("status") or {}).get("atProvider") or {}
    return (st.get("manifest") or (st.get("raw") or {}).get("manifest") or {}) or {}


def _store_key(prefix, store_name, suffix):
    clean = re.sub(r"[^A-Za-z0-9]", "_", str(store_name)).upper()
    return f"{prefix}_{clean}_{suffix}"


def _pg_key(host_name, suffix):
    clean = re.sub(r"[^A-Za-z0-9]", "_", str(host_name)).upper()
    return f"POSTGRES_{clean}_{suffix}"


def _pg_db_key(host_name, db_name, suffix):
    host_clean = re.sub(r"[^A-Za-z0-9]", "_", str(host_name)).upper()
    db_clean = re.sub(r"[^A-Za-z0-9]", "_", str(db_name)).upper()
    return f"POSTGRES_{host_clean}_{db_clean}_{suffix}"


def _uri_with_database(uri, db_name):
    if not uri:
        return ""
    parts = urlsplit(uri)
    return urlunsplit(
        (parts.scheme, parts.netloc, f"/{db_name}", parts.query, parts.fragment)
    )


def _external_pg_url(internal_url, external_host):
    if not internal_url or not external_host:
        return ""
    external_url = re.sub(r"@[^/]+", f"@{external_host}", internal_url)
    if "sslmode=" not in external_url:
        external_url += (
            "&sslmode=require" if "?" in external_url else "?sslmode=require"
        )
    if "sslnegotiation=" not in external_url:
        external_url += (
            "&sslnegotiation=direct"
            if "?" in external_url
            else "?sslnegotiation=direct"
        )
    return external_url


def compose(req: fnv1.RunFunctionRequest, rsp: fnv1.RunFunctionResponse):
    xr = _to_dict(req.observed.composite.resource)
    meta = xr.get("metadata", {}) or {}
    spec = xr.get("spec", {}) or {}

    xr_name = meta.get("name")
    xr_namespace = meta.get("namespace") or "default"

    ctx = _to_dict(req.context)
    env = ctx.get("apiextensions.crossplane.io/environment", {}) or {}
    storage_env = env.get("storage") or {}
    observed = getattr(req.observed, "resources", {}) or {}

    env_manifest = _extract_manifest(observed.get(f"workshopenvironment-{xr_name}"))
    educates_status = (env_manifest.get("status") or {}).get("educates") or {}
    workshop_ns = _safe_str(educates_status.get("namespace") or xr_name)

    obs = observed.get(f"observe-storage-secret-{xr_name}")
    data_b64 = _extract_data(obs)

    access_key = _b64get_any(
        data_b64,
        [
            "AWS_ACCESS_KEY_ID",
            "accessKey",
            "username",
            "CONSOLE_ACCESS_KEY",
            "attribute.access",
        ],
    )
    secret_key = _b64get_any(
        data_b64,
        [
            "AWS_SECRET_ACCESS_KEY",
            "secretKey",
            "password",
            "CONSOLE_SECRET_KEY",
            "attribute.secret",
        ],
    )
    session_token = _b64get_any(data_b64, ["AWS_SESSION_TOKEN", "sessionToken"])
    endpoint = _b64get_any(data_b64, ["AWS_ENDPOINT_URL"]) or storage_env.get(
        "endpoint", ""
    )
    region = _b64get_any(data_b64, ["AWS_REGION"]) or storage_env.get("region", "")
    rtype = storage_env.get("type", "")
    provider = storage_env.get("provider", "")
    force_path_style = str(storage_env.get("forcePathStyle", "true")).lower()

    if not access_key or not secret_key:
        return

    # Build the rclone configuration for the runtime Secret.
    config_data = (
        f"[{access_key}]\n"
        f"type = {rtype}\n"
        f"provider = {provider}\n"
        f"endpoint = {endpoint}\n"
        f"region = {region}\n"
        f"access_key_id = {access_key}\n"
        f"secret_access_key = {secret_key}\n"
        f"force_path_style = {force_path_style}\n"
    )

    manifest = _render_template(
        req,
        "datalab-secret/manifest",
        metadata_name=f"{xr_name}-datalab",
        xr_namespace=xr_namespace,
        access_key=access_key,
        config_data=config_data,
        secret_key=secret_key,
        region=region,
        endpoint=endpoint,
        force_path_style=force_path_style,
    )

    if session_token:
        manifest["stringData"]["AWS_SESSION_TOKEN"] = session_token

    aws_credentials = (
        "[default]\n"
        f"aws_access_key_id = {access_key}\n"
        f"aws_secret_access_key = {secret_key}\n"
    )
    if session_token:
        aws_credentials += f"aws_session_token = {session_token}\n"
    manifest["stringData"]["aws-credentials"] = aws_credentials

    oauth_data = _extract_data(observed.get(f"observe-oauth-client-secret-{xr_name}"))
    client_secret = _b64get_any(
        oauth_data, ["clientSecret", "client_secret", "attribute.client_secret"]
    )
    if client_secret:
        manifest["stringData"]["OAUTH2_CLIENT_ID"] = (
            _b64get_any(oauth_data, ["clientID", "client_id", "attribute.client_id"])
            or xr_name
        )
        manifest["stringData"]["OAUTH2_CLIENT_SECRET"] = client_secret

    doc_stores = spec.get("documentStores") or {}
    if isinstance(doc_stores, dict):
        for store_name in sorted(doc_stores.keys()):
            if not isinstance(store_name, str) or not store_name.strip():
                continue
            store = store_name.strip()
            host = f"mongodb-{store}-svc.{workshop_ns}.svc"
            user = f"{store}-app"
            manifest["stringData"][_store_key("MONGO", store, "HOST")] = host
            manifest["stringData"][_store_key("MONGO", store, "PORT")] = "27017"
            manifest["stringData"][_store_key("MONGO", store, "DATABASE")] = store
            manifest["stringData"][_store_key("MONGO", store, "AUTH_SOURCE")] = "admin"
            manifest["stringData"][_store_key("MONGO", store, "USER")] = user
            auth_data = _extract_data(
                observed.get(f"observe-mongodb-auth-secret-{xr_name}-{store}")
            )
            pwd = _b64get_any(auth_data, ["password"])
            if pwd:
                manifest["stringData"][_store_key("MONGO", store, "PASSWORD")] = pwd
                manifest["stringData"][_store_key("MONGO", store, "URI")] = (
                    f"mongodb://{user}:{pwd}@{host}:27017/{store}?authSource=admin"
                )

    cache_stores = spec.get("cacheStores") or {}
    if isinstance(cache_stores, dict):
        for store_name in sorted(cache_stores.keys()):
            if not isinstance(store_name, str) or not store_name.strip():
                continue
            store = store_name.strip()
            host = f"{store}.{workshop_ns}.svc"
            manifest["stringData"][_store_key("REDIS", store, "HOST")] = host
            manifest["stringData"][_store_key("REDIS", store, "PORT")] = "6379"
            manifest["stringData"][_store_key("REDIS", store, "USER")] = "default"
            manifest["stringData"][_store_key("REDIS", store, "DATABASE")] = "0"
            auth_data = _extract_data(
                observed.get(f"observe-redis-auth-secret-{xr_name}-{store}")
            )
            pwd = _b64get_any(auth_data, ["password"])
            if pwd:
                manifest["stringData"][_store_key("REDIS", store, "PASSWORD")] = pwd
                manifest["stringData"][_store_key("REDIS", store, "URL")] = (
                    f"redis://default:{pwd}@{host}:6379/0"
                )

    vector_stores = spec.get("vectorStores") or {}
    if isinstance(vector_stores, dict):
        for store_name in sorted(vector_stores.keys()):
            if not isinstance(store_name, str) or not store_name.strip():
                continue
            store = store_name.strip()
            host = f"qdrant-{store}.{workshop_ns}.svc"
            manifest["stringData"][_store_key("QDRANT", store, "HOST")] = host
            manifest["stringData"][_store_key("QDRANT", store, "PORT")] = "6333"
            manifest["stringData"][_store_key("QDRANT", store, "GRPC_PORT")] = "6334"
            manifest["stringData"][_store_key("QDRANT", store, "URL")] = (
                f"http://{host}:6333"
            )
            auth_data = _extract_data(
                observed.get(f"observe-qdrant-auth-secret-{xr_name}-{store}")
            )
            api_key = _b64get_any(auth_data, ["apiKey"])
            read_key = _b64get_any(auth_data, ["readApiKey"])
            if api_key:
                manifest["stringData"][_store_key("QDRANT", store, "API_KEY")] = api_key
            if read_key:
                manifest["stringData"][_store_key("QDRANT", store, "READ_API_KEY")] = (
                    read_key
                )

    db_hosts = spec.get("databases") or {}
    if isinstance(db_hosts, dict):
        db_env = env.get("database") or {}
        gateway_env = db_env.get("tlsRoute") or {}

        gateway_parent_name = _safe_str(gateway_env.get("parentName") or "")
        gateway_parent_ns = _safe_str(gateway_env.get("parentNamespace") or "")
        gateway_section = _safe_str(gateway_env.get("sectionName") or "")
        has_gateway_parent = bool(
            gateway_parent_name and gateway_parent_ns and gateway_section
        )

        ingress_env = env.get("ingress") or {}
        ingress_domain = ingress_env.get("domain", "default")

        for host_key in sorted(list(db_hosts.keys())):
            if not isinstance(host_key, str) or not host_key.strip():
                continue
            host_cfg = db_hosts.get(host_key) or {}
            if not isinstance(host_cfg, dict):
                continue

            cluster_name = host_key.strip()
            dbnames = [
                _safe_str(x) for x in list(host_cfg.get("names") or []) if _safe_str(x)
            ]
            if not dbnames:
                continue

            host_obs = observed.get(f"observe-database-secret-{xr_name}-{cluster_name}")
            host_data_b64 = _extract_data(host_obs)

            host = (
                _b64get_any(host_data_b64, ["host"])
                or f"{cluster_name}-primary.{workshop_ns}.svc"
            )
            port = _b64get_any(host_data_b64, ["port"]) or "5432"
            user = _b64get_any(host_data_b64, ["user"]) or "postgres"
            password = _b64get_any(host_data_b64, ["password"]) or ""
            internal_url = _b64get_any(host_data_b64, ["uri"]) or ""

            manifest["stringData"][_pg_key(cluster_name, "HOST")] = host
            manifest["stringData"][_pg_key(cluster_name, "PORT")] = port
            manifest["stringData"][_pg_key(cluster_name, "USER")] = user
            manifest["stringData"][_pg_key(cluster_name, "PASSWORD")] = password
            manifest["stringData"][_pg_key(cluster_name, "DATABASES")] = ",".join(
                dbnames
            )

            host_ext = ""
            if has_gateway_parent:
                host_ext = f"{cluster_name}-{workshop_ns}.{ingress_domain}:443"
                manifest["stringData"][_pg_key(cluster_name, "HOST_EXTERNAL")] = (
                    host_ext.split(":")[0]
                )

            for dbname in dbnames:
                db_url = _uri_with_database(internal_url, dbname)
                if not db_url and password:
                    db_url = f"postgresql://{user}:{password}@{host}:{port}/{dbname}"
                if db_url:
                    manifest["stringData"][_pg_db_key(cluster_name, dbname, "URL")] = (
                        db_url
                    )
                if host_ext and db_url:
                    manifest["stringData"][
                        _pg_db_key(cluster_name, dbname, "URL_EXTERNAL")
                    ] = _external_pg_url(db_url, host_ext)

    key = f"secret-{xr_name}-datalab"
    rsp.desired.resources[key].resource.update(manifest)
    rsp.desired.resources[key].ready = fnv1.READY_TRUE
