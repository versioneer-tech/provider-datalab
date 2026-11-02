# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

import base64
import hashlib

from google.protobuf import json_format


def _to_dict(value):
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    return json_format.MessageToDict(value, preserving_proto_field_name=True)


def _boolish(value):
    if isinstance(value, bool):
        return value
    return str(value).lower() in ("true", "1", "yes", "on")


def _safe_str(value):
    return str(value).strip() if value is not None else ""


def _string_value(value):
    """Keep the literal string for null values in existing resource settings."""
    return str(value).strip()


def _observed_manifests(observed_resource):
    if not observed_resource or not getattr(observed_resource, "resource", None):
        return {}, {}
    resource = _to_dict(observed_resource.resource)
    at_provider = (resource.get("status") or {}).get("atProvider") or {}
    return (
        at_provider.get("manifest") or {},
        (at_provider.get("raw") or {}).get("manifest") or {},
    )


def _extract_manifest(observed_resource):
    manifest, raw_manifest = _observed_manifests(observed_resource)
    return manifest or raw_manifest


def _extract_data(observed_resource):
    manifest, raw_manifest = _observed_manifests(observed_resource)
    return (
        manifest.get("data")
        or manifest.get("stringData")
        or raw_manifest.get("data")
        or raw_manifest.get("stringData")
        or {}
    )


def _b64get_any(data, keys):
    if not data:
        return None
    for key in keys:
        value = data.get(key)
        if value is None:
            continue
        try:
            return base64.b64decode(value, validate=True).decode("utf-8")
        except Exception:
            return str(value)
    return None


def _strong_token(seed, *, suffix=":provider-datalab", length=32):
    # Keep each service's existing seed and length to prevent credential changes.
    digest = hashlib.sha256((seed + suffix).encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")[:length]


def _session_name(session, *, stringify_none=False):
    if isinstance(session, dict):
        return _safe_str(session.get("name") or "")
    return _string_value(session) if stringify_none else _safe_str(session)


def _session_state(session):
    state = (
        _safe_str(session.get("state") or "started").lower()
        if isinstance(session, dict)
        else "started"
    )
    return {"running": "started", "paused": "stopped"}.get(state, state)
