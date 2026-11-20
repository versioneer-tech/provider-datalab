# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

import base64
import hashlib
import json
import re
from decimal import Decimal

from crossplane.function import request, response
from google.protobuf import json_format


def _to_dict(value):
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    return json_format.MessageToDict(value, preserving_proto_field_name=True)


def set_response_ttl(req, rsp, default_seconds):
    rsp.meta.ttl.FromSeconds(default_seconds)
    environment = (
        _to_dict(req.context).get("apiextensions.crossplane.io/environment") or {}
    )
    datalab = environment.get("datalab") or {}
    if not isinstance(datalab, dict):
        response.fatal(rsp, "datalab must be a mapping with optional responseTTL.")
        return False
    if "responseTTL" not in datalab:
        return True
    match = re.fullmatch(r"([1-9][0-9]*)(s|m|h)", str(datalab["responseTTL"]))
    if match:
        seconds = int(match[1]) * {"s": 1, "m": 60, "h": 3600}[match[2]]
        if seconds <= (2**63 - 1) // 1_000_000_000:
            rsp.meta.ttl.FromSeconds(seconds)
            return True
    response.fatal(
        rsp,
        "datalab.responseTTL must be a positive whole duration, such as 30s, 5m, "
        "or 1h, within the signed 64-bit nanosecond limit.",
    )
    return False


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


def _extract_manifest(observed_resource):
    if not observed_resource or not getattr(observed_resource, "resource", None):
        return {}
    resource = _to_dict(observed_resource.resource)
    at_provider = (resource.get("status") or {}).get("atProvider") or {}
    return at_provider.get("manifest") or (at_provider.get("raw") or {}).get("manifest") or {}


def require_secret(req, rsp, key, name, namespace):
    response.require_resources(
        rsp, name=key, api_version="v1", kind="Secret",
        namespace=namespace, match_name=name,
    )
    secret = request.get_required_resource(req, key) or {}
    return {} if (secret.get("metadata") or {}).get("deletionTimestamp") else secret


def _secret_manifest(req, rsp, key):
    # The Object supplies the target reference and watches, not credential data.
    desired = rsp.desired.resources.get(key)
    body = _to_dict(desired.resource) if desired else {}
    metadata = (body.get("spec", {}).get("forProvider", {}).get("manifest", {}).get("metadata") or {})
    name, namespace = metadata.get("name"), metadata.get("namespace")
    if not name or not namespace:
        return {}
    return require_secret(req, rsp, "source-" + key, name, namespace)


def _extract_data(req, rsp, key):
    manifest = _secret_manifest(req, rsp, key)
    return manifest.get("data") or manifest.get("stringData") or {}


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
