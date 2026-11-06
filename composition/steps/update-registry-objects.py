# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

import hashlib
import json

from composition.helpers import (
    _b64get_any,
    _boolish,
    _extract_data,
    _extract_manifest,
    _http_route_timeouts,
    _safe_str,
    _strong_token,
    _to_dict,
)
from composition.render import _render_template


def compose(req, rsp):
    xr = _to_dict(req.observed.composite.resource)
    meta = xr["metadata"]
    name, namespace = meta["name"], meta.get("namespace") or "default"
    env = _to_dict(req.context).get("apiextensions.crossplane.io/environment") or {}
    registry_image = _safe_str((env.get("images") or {}).get("registry")) or "registry:3.1.2"
    if not _boolish(((env.get("defaults") or {}).get("registry") or {}).get("enabled", True)):
        return
    observed = req.observed.resources
    runtime = (_extract_manifest(observed.get(f"workshopenvironment-{name}")).get("status") or {}).get("educates") or {}
    runtime_namespace = runtime.get("namespace")
    if not runtime_namespace:
        return

    def emit(suffix, manifest, readiness=None):
        key = f"registry-{suffix}-{name}"
        rsp.desired.resources[key].resource.update(_render_template(
            req, "common/object", key=key, xr_namespace=namespace, manifest=manifest,
            readiness=readiness or {"policy": "SuccessfulCreate"},
        ))

    auth = {"user": name, "password": _strong_token(f"{name}:registry", length=28),
            "http-secret": _strong_token(f"{name}:registry:http")}
    emit("auth-secret", {
        "apiVersion": "v1", "kind": "Secret",
        "metadata": {"name": "registry-auth", "namespace": runtime_namespace},
        "type": "Opaque", "stringData": auth,
    })
    storage_data = _extract_data(observed.get(f"observe-runtime-storage-secret-{name}"))
    if not _b64get_any(storage_data, ["aws-credentials"]):
        return
    storage = env.get("storage") or {}
    endpoint = _b64get_any(storage_data, ["AWS_ENDPOINT_URL"]) or storage.get("endpoint", "")
    config = {
        "version": 0.1,
        "log": {"level": "info"},
        "storage": {
            "s3": {"bucket": name, "region": _b64get_any(storage_data, ["AWS_REGION"]) or storage.get("region") or "us-east-1",
                   "forcepathstyle": _boolish(
                       _b64get_any(storage_data, ["AWS_S3_FORCE_PATH_STYLE"]) or storage.get("forcePathStyle", True)),
                   "secure": not endpoint.startswith("http://")},
            # Keep downloads on the authenticated registry route.
            "redirect": {"disable": True},
        },
        "http": {"addr": "0.0.0.0:5000", "relativeurls": True,
                 "debug": {"addr": "0.0.0.0:5001"}},
        "auth": {"htpasswd": {"realm": "Datalab registry", "path": "/auth/htpasswd"}},
        "health": {"storagedriver": {"enabled": True, "interval": "10s", "threshold": 3}},
    }
    config_text = json.dumps(config, indent=2, sort_keys=True)
    checksum = hashlib.sha256(json.dumps([storage_data, auth, config_text], sort_keys=True).encode()).hexdigest()
    labels = {"app.kubernetes.io/name": "registry", "app.kubernetes.io/instance": name}
    emit("config", _render_template(req, "registry/config", runtime_namespace=runtime_namespace, config=config_text))
    emit("deployment", _render_template(
        req, "registry/deployment", runtime_namespace=runtime_namespace, labels=labels,
        registry_image=registry_image,
        checksum=checksum, storage_secret_name=f"{name}-datalab",
    ), {"policy": "DeriveFromCelQuery", "celQuery":
        "has(object.status) && has(object.status.observedGeneration) && object.status.observedGeneration >= object.metadata.generation && has(object.status.availableReplicas) && object.status.availableReplicas >= 1"})
    emit("service", _render_template(req, "registry/service", runtime_namespace=runtime_namespace, labels=labels))
    emit("networkpolicy", {
        "apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy",
        "metadata": {"name": "registry", "namespace": runtime_namespace},
        "spec": {"podSelector": {"matchLabels": labels}, "policyTypes": ["Ingress"],
                 "ingress": [{"ports": [{"protocol": "TCP", "port": 5000}]}]},
    })
    ingress, gateway = env.get("ingress") or {}, env.get("httpRoute") or {}
    hostname = f"{name}.{ingress.get('domain', 'default')}"
    backend = {"name": "registry", "port": 5000}
    if _boolish(gateway.get("enabled")):
        parent = {"name": gateway["parentName"], "namespace": gateway["parentNamespace"],
                  "sectionName": gateway["sectionName"]}
        emit("route", {
            "apiVersion": "gateway.networking.k8s.io/v1", "kind": "HTTPRoute",
            "metadata": {"name": "registry", "namespace": runtime_namespace},
            "spec": {"parentRefs": [parent], "hostnames": [hostname], "rules": [
                {"matches": [{"path": {"type": "PathPrefix", "value": "/v2"}}],
                 "backendRefs": [backend], "timeouts": _http_route_timeouts(env)},
            ]},
        }, {"policy": "DeriveFromCelQuery", "celQuery":
            f"has(object.status) && has(object.status.parents) && object.status.parents.exists(p, p.parentRef.name == {json.dumps(parent['name'])} && has(p.parentRef.namespace) && p.parentRef.namespace == {json.dumps(parent['namespace'])} && has(p.parentRef.sectionName) && p.parentRef.sectionName == {json.dumps(parent['sectionName'])} && has(p.conditions) && p.conditions.exists(c, c.type == 'Accepted' && c.status == 'True' && c.observedGeneration == object.metadata.generation) && p.conditions.exists(c, c.type == 'ResolvedRefs' && c.status == 'True' && c.observedGeneration == object.metadata.generation))"})
    elif _boolish(ingress.get("enabled")):
        emit("ingress", {
            "apiVersion": "networking.k8s.io/v1", "kind": "Ingress",
            "metadata": {"name": "registry", "namespace": runtime_namespace,
                         "annotations": ingress.get("annotations") or {}},
            "spec": {"ingressClassName": ingress.get("class", ""), "rules": [{"host": hostname,
                "http": {"paths": [{"path": "/v2", "pathType": "Prefix", "backend": {
                    "service": {"name": "registry", "port": {"number": 5000}}}}]}}],
                "tls": [{"hosts": [hostname], "secretName": ingress.get("secret", "wildcard-tls")}]},
        })
