# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

import re
from urllib.parse import urlsplit, urlunsplit

from crossplane.function.proto.v1 import run_function_pb2 as fnv1
from composition.helpers import _b64get_any, _extract_data, _secret_data, _to_dict
from composition.render import _render_template


def _storage_values(data, config):
    access = _b64get_any(
        data,
        [
            "AWS_ACCESS_KEY_ID",
            "accessKey",
            "username",
            "CONSOLE_ACCESS_KEY",
            "attribute.access",
        ],
    )
    secret = _b64get_any(
        data,
        [
            "AWS_SECRET_ACCESS_KEY",
            "secretKey",
            "password",
            "CONSOLE_SECRET_KEY",
            "attribute.secret",
        ],
    )
    if not access or not secret:
        return {}
    endpoint = _b64get_any(data, ["AWS_ENDPOINT_URL"]) or config.get("endpoint", "")
    region = _b64get_any(data, ["AWS_REGION"]) or config.get("region", "")
    style = str(config.get("forcePathStyle", "true")).lower()
    values = {
        "AWS_ACCESS_KEY_ID": access,
        "AWS_SECRET_ACCESS_KEY": secret,
        "AWS_ENDPOINT_URL": endpoint,
        "AWS_REGION": region,
        "AWS_S3_FORCE_PATH_STYLE": style,
        "remote": access,
        "remotePath": "/",
        "configData": (
            f"[{access}]\ntype = {config.get('type', '')}\nprovider = {config.get('provider', '')}\n"
            f"endpoint = {endpoint}\nregion = {region}\naccess_key_id = {access}\n"
            f"secret_access_key = {secret}\nforce_path_style = {style}\n"
        ),
        "aws-credentials": f"[default]\naws_access_key_id = {access}\naws_secret_access_key = {secret}\n",
    }
    token = _b64get_any(data, ["AWS_SESSION_TOKEN", "sessionToken"])
    if token:
        values["AWS_SESSION_TOKEN"] = token
        values["aws-credentials"] += f"aws_session_token = {token}\n"
    return values


def _postgres_values(data, name, store, config, env):
    host = _b64get_any(data, ["host"]) or f"{store}-primary.{name}.svc"
    values = {
        "host": host,
        "port": _b64get_any(data, ["port"]) or "5432",
        "user": _b64get_any(data, ["user"]) or "postgres",
        "password": _b64get_any(data, ["password"]) or "",
        "databases": ",".join(config.get("names") or []),
    }
    route = (env.get("database") or {}).get("tlsRoute") or {}
    external = ""
    if all(route.get(key) for key in ("parentName", "parentNamespace", "sectionName")):
        external = (
            f"{store}-{name}.{(env.get('ingress') or {}).get('domain', 'default')}"
        )
        values["host_external"] = external
    uri = _b64get_any(data, ["uri"]) or ""
    for database in config.get("names") or []:
        if uri:
            parts = urlsplit(uri)
            url = urlunsplit(
                (
                    parts.scheme,
                    parts.netloc,
                    f"/{database}",
                    parts.query,
                    parts.fragment,
                )
            )
        elif values["password"]:
            url = f"postgresql://{values['user']}:{values['password']}@{host}:{values['port']}/{database}"
        else:
            continue
        # Keep the published keys used by existing per-service consumers.
        key = re.sub(r"[^A-Za-z0-9]", "_", database).lower() + "_url"
        values[key] = url
        if external:
            parts = urlsplit(url)
            query = parts.query
            for option in ("sslmode=require", "sslnegotiation=direct"):
                if option.split("=")[0] + "=" not in query:
                    query += ("&" if query else "") + option
            values[key + "_external"] = urlunsplit(
                (
                    parts.scheme,
                    parts.netloc.rsplit("@", 1)[0] + "@" + external + ":443",
                    parts.path,
                    query,
                    parts.fragment,
                )
            )
    return values


def compose(req, rsp):
    xr = _to_dict(req.observed.composite.resource)
    meta = xr["metadata"]
    spec = xr.get("spec") or {}
    name = meta["name"]
    namespace = meta.get("namespace") or "default"
    env = _to_dict(req.context).get("apiextensions.crossplane.io/environment") or {}
    observed = req.observed.resources
    connections = []

    def publish(connection_name, kind, values, complete, endpoint=""):
        secret_name = f"{name}-{connection_name}"
        key = f"connection-{secret_name}"
        current = _secret_data(observed.get(key))
        desired_data = _secret_data({"stringData": values})
        ready = bool(complete and values and current == desired_data)
        if complete and values:
            rsp.desired.resources[key].resource.update(
                _render_template(
                    req,
                    "publish-connections/secret",
                    secret_name=secret_name,
                    namespace=namespace,
                    name=name,
                    connection_name=connection_name,
                    key=key,
                    values=values,
                )
            )
            rsp.desired.resources[key].ready = fnv1.READY_TRUE
        connections.append(
            {
                "name": connection_name,
                "type": kind,
                "ready": ready,
                "secretRef": {"name": secret_name, "namespace": namespace},
                **({"endpoint": endpoint} if endpoint else {}),
            }
        )

    storage = _storage_values(
        _extract_data(observed.get(f"observe-storage-secret-{name}")),
        env.get("storage") or {},
    )
    publish("s3", "s3", storage, bool(storage), storage.get("AWS_ENDPOINT_URL", ""))
    for store, config in sorted((spec.get("databases") or {}).items()):
        values = _postgres_values(
            _extract_data(observed.get(f"observe-database-secret-{name}-{store}")),
            name,
            store,
            config,
            env,
        )
        publish(
            f"postgres-{store}",
            "postgres",
            values,
            bool(values["password"]),
            values["host"],
        )
    for field, backend, kind in (
        ("documentStores", "mongodb", "mongo"),
        ("cacheStores", "redis", "redis"),
    ):
        for store in sorted(spec.get(field) or {}):
            password = (
                _b64get_any(
                    _extract_data(
                        observed.get(f"observe-{backend}-auth-secret-{name}-{store}")
                    ),
                    ["password"],
                )
                or ""
            )
            if kind == "mongo":
                host = f"mongodb-{store}-svc.{name}.svc"
                values = {
                    "host": host,
                    "port": "27017",
                    "database": store,
                    "auth_source": "admin",
                    "user": f"{store}-app",
                    "password": password,
                }
                values["uri"] = (
                    f"mongodb://{store}-app:{password}@{host}:27017/{store}?authSource=admin"
                )
            else:
                host = f"{store}.{name}.svc"
                values = {
                    "host": host,
                    "port": "6379",
                    "database": "0",
                    "user": "default",
                    "password": password,
                    "url": f"redis://default:{password}@{host}:6379/0",
                }
            publish(f"{kind}-{store}", kind, values, bool(password), host)
    rsp.desired.composite.resource.update({"status": {"connections": connections}})
