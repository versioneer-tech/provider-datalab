# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

import base64 as _base64
import hashlib as _hashlib
from crossplane.function.proto.v1 import run_function_pb2 as fnv1
from google.protobuf import json_format as _json_format


def _to_dict(s):
    if s is None:
        return {}
    return (
        s
        if isinstance(s, dict)
        else _json_format.MessageToDict(s, preserving_proto_field_name=True)
    )


def _safe_str(v):
    return str(v).strip() if v is not None else ""


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


def compose(req: fnv1.RunFunctionRequest, rsp: fnv1.RunFunctionResponse):
    xr = _to_dict(req.observed.composite.resource)
    meta = xr.get("metadata", {}) or {}

    xr_name = meta.get("name")
    xr_namespace = meta.get("namespace") or "default"

    observed = getattr(req.observed, "resources", {}) or {}
    oauth_data = _extract_data(observed.get(f"observe-oauth-client-secret-{xr_name}"))
    client_secret = _b64get_any(
        oauth_data, ["clientSecret", "client_secret", "attribute.client_secret"]
    )
    if not client_secret:
        return
    client_id = (
        _b64get_any(oauth_data, ["clientID", "client_id", "attribute.client_id"])
        or xr_name
    )
    cookie_secret = _hashlib.sha256(client_secret.encode("utf-8")).hexdigest()[:32]

    env_manifest = _extract_manifest(observed.get(f"workshopenvironment-{xr_name}"))
    educates_status = (env_manifest.get("status") or {}).get("educates") or {}
    workshop_ns = _safe_str(educates_status.get("namespace") or xr_name)

    secret_name = f"{xr_name}-oauth2-client"
    key = f"oauth2-client-secret-{xr_name}"
    manifest = _render_template(
        req,
        "oauth2-client-secret/manifest",
        secret_name=secret_name,
        workshop_ns=workshop_ns,
        client_id=client_id,
        client_secret=client_secret,
        cookie_secret=cookie_secret,
    )
    rsp.desired.resources[key].resource.update(
        _render_template(
            req,
            "oauth2-client-secret/object",
            key=key,
            xr_namespace=xr_namespace,
            manifest=manifest,
        )
    )
