# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

import json
import re
from urllib.parse import quote, urlsplit, urlunsplit

from crossplane.function.proto.v1 import run_function_pb2 as fnv1
from composition.helpers import _b64get_any, _extract_data, _postgres_connection_data, _stores, _to_dict
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
        "aws-credentials": f"[default]\naws_access_key_id = {access}\naws_secret_access_key = {secret}\n",
    }
    token = _b64get_any(data, ["AWS_SESSION_TOKEN", "sessionToken"])
    if token:
        values["AWS_SESSION_TOKEN"] = token
        values["aws-credentials"] += f"aws_session_token = {token}\n"
    return values


def _postgres_values(data, name, store, config, env):
    data = _postgres_connection_data(data, store, name)
    host = f"{store}-rw.{name}.svc"
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
    uri = _b64get_any(data, ["fqdn-uri", "uri"]) or ""
    for database in config.get("names") or []:
        if uri:
            parts = urlsplit(uri)
            url = urlunsplit(
                (
                    parts.scheme,
                    parts.netloc,
                    "/" + quote(database, safe=""),
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

    def publish(connection_name, values, complete):
        secret_name = f"{name}-{connection_name}"
        key = f"connection-{secret_name}"
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

    storage = _storage_values(
        _extract_data(req, rsp, f"observe-storage-secret-{name}"),
        env.get("storage") or {},
    )
    publish("s3", storage, bool(storage))
    for store, config in sorted(_stores(spec, "postgres").items()):
        values = _postgres_values(
            _extract_data(req, rsp, f"observe-database-secret-{name}-{store}"),
            name,
            store,
            config,
            env,
        )
        values["names"] = json.dumps(config["names"])
        publish(
            f"postgres-{store}",
            values,
            bool(values["password"]),
        )
    for backend, kind in (
        ("valkey", "valkey"),
    ):
        for store, config in sorted(_stores(spec, kind).items()):
            names = config["names"]
            password = (
                _b64get_any(
                    _extract_data(
                        req, rsp, f"observe-{backend}-auth-secret-{name}-{store}"
                    ),
                    ["password"],
                )
                or ""
            )
            host = f"{store}.{name}.svc"
            values = {
                "host": host,
                "port": "6379",
                "database": "0",
                "user": "default",
                "password": password,
                "url": f"redis://default:{password}@{host}:6379/0",
                "prefixes": json.dumps({name: name + ":" for name in names}),
            }
            values["names"] = json.dumps(names)
            publish(f"{kind}-{store}", values, bool(password))
