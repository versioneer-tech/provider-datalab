# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

import base64
import hashlib
import json
import re
from decimal import Decimal

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


def _duration_milliseconds(value, setting):
    text = _safe_str(value)
    if not re.fullmatch(r"(?:[0-9]{1,5}(?:ms|h|m|s)){1,4}", text):
        raise ValueError(f"{setting} must be a duration, such as 3600s, 1h30m, or 0s.")
    units = {"h": 3600000, "m": 60000, "s": 1000, "ms": 1}
    return sum(int(number) * units[unit] for number, unit in re.findall(r"([0-9]+)(ms|h|m|s)", text))


def _http_route_timeouts(environment):
    configured = (environment.get("httpRoute") or {}).get("timeouts")
    if configured is None:
        configured = {}
    if not isinstance(configured, dict):
        raise ValueError("httpRoute.timeouts must contain request and backendRequest durations.")
    request_timeout = _safe_str(configured.get("request", "3600s"))
    timeouts = {"request": request_timeout,
                "backendRequest": _safe_str(configured.get("backendRequest", request_timeout))}
    request, backend = (
        _duration_milliseconds(timeouts[key], f"httpRoute.timeouts.{key}")
        for key in ("request", "backendRequest")
    )
    if request and backend > request:
        raise ValueError("httpRoute.timeouts.backendRequest must not exceed request; use request: 0s for no request timeout.")
    return timeouts


def _string_value(value):
    """Keep the literal string for null values in existing resource settings."""
    return str(value).strip()


def _backup_enabled(value):
    quantity = str(value or "0").strip()
    match = re.fullmatch(
        r"([+]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+))(?:[eE][+-]?[0-9]+|[numkMGTPE]|[KMGTPE]i)?",
        quantity,
    )
    if not match:
        raise ValueError("backupStorage must be a non-negative Kubernetes quantity")
    return Decimal(match[1]) > 0


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


def _resource_name(*parts, limit=63):
    name = "-".join(parts)
    if len(name) <= limit and (
        len(parts) == 1 or all("-" not in part for part in parts)
    ):
        return name
    # Keep component boundaries distinct when instance and profile names have hyphens.
    digest = hashlib.sha256(json.dumps(parts).encode()).hexdigest()[:10]
    return name[: limit - 11].rstrip("-") + "-" + digest


def _vcluster_profile(name, instance, group):
    return _resource_name(name, "vcluster", instance, group, limit=55)


def _vcluster_role(instance, group):
    return f"vcluster_{instance}_{group}"


def _vcluster_groups(config):
    groups = {group["name"]: group for group in config.get("groups") or []}
    groups["cluster-admin"] = {
        "name": "cluster-admin", "namespace": "*", "role": "cluster-admin"
    }
    return [groups[name] for name in sorted(groups)]


def _vcluster_exchange_groups(config):
    groups = {
        group["name"]: group for group in config.get("groups") or []
        if group["name"] != "cluster-admin"
    }
    return [groups[name] for name in sorted(groups)]


def _runtime_namespace(req, name):
    environment = _extract_manifest(
        req.observed.resources.get(f"workshopenvironment-{name}")
    )
    return ((environment.get("status") or {}).get("educates") or {}).get(
        "namespace"
    ) or ""
