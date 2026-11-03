# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

import base64 as _base64
import hashlib as _hashlib

from crossplane.function.proto.v1 import run_function_pb2 as fnv1

from composition.helpers import (
    _b64get_any,
    _extract_data,
    _extract_manifest,
    _safe_str,
    _to_dict,
)
from composition.render import _render_template


def compose(req: fnv1.RunFunctionRequest, rsp: fnv1.RunFunctionResponse):
    xr = _to_dict(req.observed.composite.resource)
    metadata = xr.get("metadata", {}) or {}

    xr_name = metadata.get("name")
    xr_namespace = metadata.get("namespace") or "default"

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

    environment_manifest = _extract_manifest(
        observed.get(f"workshopenvironment-{xr_name}")
    )
    educates_status = (environment_manifest.get("status") or {}).get("educates") or {}
    workshop_namespace = _safe_str(educates_status.get("namespace") or xr_name)

    secret_name = f"{xr_name}-oauth2-client"
    key = f"oauth2-client-secret-{xr_name}"
    manifest = _render_template(
        req,
        "oauth2-client-secret/manifest",
        secret_name=secret_name,
        workshop_ns=workshop_namespace,
        data={
            key: _base64.b64encode(value.encode("utf-8")).decode("ascii")
            for key, value in {
                "client_id": client_id,
                "client_secret": client_secret,
                "cookie_secret": cookie_secret,
            }.items()
        },
    )
    rsp.desired.resources[key].resource.update(
        _render_template(
            req,
            "common/object",
            key=key,
            xr_namespace=xr_namespace,
            manifest=manifest,
            readiness={"policy": "SuccessfulCreate"},
        )
    )
