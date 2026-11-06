# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

import base64
import hashlib
import json
from composition.helpers import (
    _resource_name,
    _to_dict,
    _vcluster_groups,
    _vcluster_profile,
)
from composition.render import _render_template

CREDENTIAL_HELPER = _embedded_script("scripts/vcluster-credentials.py")


def compose(req, rsp):
    xr = _to_dict(req.observed.composite.resource)
    spec = xr.get("spec") or {}
    status = (
        _to_dict(rsp.desired.composite.resource).get("status") or xr.get("status") or {}
    )
    instances = spec.get("vclusters") or {}
    if not instances and not any(
        c.get("type") == "vcluster" for c in status.get("connections", [])
    ):
        return
    meta = xr["metadata"]
    name = meta["name"]
    namespace = meta.get("namespace") or "default"
    env = _to_dict(req.context).get("apiextensions.crossplane.io/environment") or {}
    connections = [
        c for c in status.get("connections", []) if c.get("type") != "vcluster"
    ]

    def ready(key):
        observed = req.observed.resources.get(key)
        body = _to_dict(observed.resource) if observed else {}
        return any(
            c.get("type") == "Ready" and c.get("status") == "True"
            for c in body.get("status", {}).get("conditions", [])
        )

    for instance, config in sorted(instances.items()):
        endpoint = f"https://{name}.{env['ingress']['domain']}/.{instance}"
        cluster = {"server": endpoint}
        gateway_ca = (env.get("ingress") or {}).get("certificateAuthority")
        if gateway_ca:
            cluster["certificate-authority-data"] = base64.b64encode(
                gateway_ca.encode()
            ).decode()
        issuer = str((env.get("iam") or {})["issuerURL"]).rstrip("/")
        for group in _vcluster_groups(config):
            profile = _vcluster_profile(name, instance, group["name"])
            connection_name = _resource_name("vcluster", instance, group["name"])
            # New names let Crossplane delete old Secrets with stored credentials.
            secret_name = _resource_name(name, "vcluster", instance, group["name"], "connection")
            if group["name"] == "cluster-admin":
                args = ["-c", CREDENTIAL_HELPER, "--issuer", issuer, "--client-id", name]
                issuer_ca = (env.get("vcluster") or {}).get("issuerCA")
                if issuer_ca:
                    args += ["--issuer-ca-data", base64.b64encode(issuer_ca.encode()).decode()]
            else:
                args = ["-c", CREDENTIAL_HELPER, "--token-only"]
            binding = hashlib.sha256(
                f"{group['name']}:{group['namespace']}:{group['role']}".encode()
            ).hexdigest()[:12]
            scope_resource = (
                _resource_name(name, "interactive") if group["name"] == "cluster-admin"
                else _resource_name(profile, "scope")
            )
            complete = all(
                ready(key)
                for key in [
                    *(
                        _resource_name("vcluster", name, instance, suffix)
                        for suffix in ("statefulset", "route", "backend-tls")
                    ),
                    _resource_name(
                        "vcluster", name, instance, "access", f"binding-{binding}"
                    ),
                    f"keycloak-client-{name}",
                    f"keycloak-vcluster-role-{profile}",
                    f"keycloak-optional-scope-{scope_resource}",
                    "keycloak-optional-role-" + _resource_name(scope_resource, profile),
                    f"keycloak-defaultScopes-{name}",
                    f"keycloak-optionalScopes-{name}",
                    "keycloak-selected-role-" + _resource_name(scope_resource, profile),
                    f"keycloak-selected-role-{name}-ws-api",
                    f"keycloak-selected-roles-{name}",
                ]
            )
            kubeconfig = _render_template(
                req,
                "vcluster/client-config",
                name=_resource_name(name, instance),
                cluster=cluster,
                profile=profile,
                contexts_0_context_namespace=(
                    "default" if group["namespace"] == "*" else group["namespace"]
                ),
                interactive_mode="IfAvailable" if group["name"] == "cluster-admin" else "Never",
                args=args,
            )
            key = _resource_name("connection", secret_name)
            rsp.desired.resources[key].resource.update(
                _render_template(
                    req,
                    "secrets/connection",
                    key=key,
                    name=name,
                    namespace=namespace,
                    secret_name=secret_name,
                    connection_name=connection_name,
                    values={key: base64.b64encode(value.encode()).decode() for key, value in {
                        "kubeconfig": json.dumps(kubeconfig, indent=2, sort_keys=True),
                        "client-id": name,
                        "issuer-url": issuer,
                    }.items()},
                )
            )
            connections.append(
                {
                    "name": connection_name,
                    "type": "vcluster",
                    "instance": instance,
                    "group": group["name"],
                    "targetNamespace": group["namespace"],
                    "role": group["role"],
                    "endpoint": endpoint,
                    "ready": complete,
                    "secretRef": {"name": secret_name, "namespace": namespace},
                }
            )
    status["connections"] = connections
    rsp.desired.composite.resource.update({"status": status})
