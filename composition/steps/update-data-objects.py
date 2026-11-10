# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

import copy as _copy
import hashlib as _hashlib
import json as _json
import shlex as _shlex

from crossplane.function.proto.v1 import run_function_pb2 as fnv1

from composition.helpers import (
    _b64get_any,
    _boolish,
    _extract_manifest,
    _http_route_timeouts,
    _safe_str,
    _to_dict,
)
from composition.render import _render_template


def _extract_secret_data(objres):
    manifest = _extract_manifest(objres)
    data = manifest.get("data") or {}
    return data if isinstance(data, dict) else {}


def compose(req: fnv1.RunFunctionRequest, rsp: fnv1.RunFunctionResponse):
    xr = _to_dict(req.observed.composite.resource)
    metadata = xr.get("metadata", {}) or {}
    spec = xr.get("spec", {}) or {}

    xr_name = metadata.get("name")
    xr_namespace = metadata.get("namespace") or "default"

    context = _to_dict(req.context)
    environment = context.get("apiextensions.crossplane.io/environment", {}) or {}
    images = environment.get("images") or {}
    package_r_image = _safe_str(images.get("packageR")) or "ghcr.io/versioneer-tech/package-r:vnext.1.1.0"
    rclone_image = _safe_str(images.get("rclone")) or "rclone/rclone:1.71.0"
    oauth2_proxy_image = _safe_str(images.get("oauth2Proxy")) or "quay.io/oauth2-proxy/oauth2-proxy:v7.15.4"
    data_config = (environment.get("defaults") or {}).get("data") or {}
    data_enabled = data_config.get("enabled")
    if data_enabled is None:
        data_enabled = True
    if not _boolish(data_enabled):
        return

    read_only = data_config.get("readOnlyMount")
    if read_only is None:
        read_only = False
    write_permission_args = []
    if not _boolish(read_only):
        write_permission_args = [
            "--perm.create=true",
            "--perm.delete=true",
            "--perm.modify=true",
            "--perm.rename=true",
        ]

    observed = getattr(req.observed, "resources", {}) or {}
    runtime_namespace = xr_name

    storage_secret_name = f"{xr_name}-storage"
    runtime_secret_key = f"observe-runtime-storage-secret-{xr_name}"
    runtime_secret_data = _extract_secret_data(observed.get(runtime_secret_key))
    if not runtime_secret_data:
        return

    checksum_keys = (
        "aws-credentials",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_ENDPOINT_URL",
        "AWS_REGION",
    )
    checksum_input = "\n".join(
        f"{key}={_safe_str(runtime_secret_data.get(key))}" for key in checksum_keys
    )
    storage_secret_checksum = _hashlib.sha256(
        checksum_input.encode("utf-8")
    ).hexdigest()

    iam = environment.get("iam") or {}
    ingress = environment.get("ingress") or {}
    storage = environment.get("storage") or {}
    network = environment.get("network") or {}
    excluded_network_policies = {
        _safe_str(name)
        for name in (network.get("excludePolicies") or [])
        if _safe_str(name)
    }
    service_cidr = _safe_str(network.get("serviceCIDR"))
    pod_cidrs = [
        _safe_str(cidr) for cidr in (network.get("podCIDRs") or []) if _safe_str(cidr)
    ]
    realm = _safe_str(iam.get("realm") or "default")
    issuer_url = _safe_str(iam.get("issuerURL"))
    internal_iam_url = _safe_str(iam.get("internalURL"))
    iam_namespace = _safe_str(iam.get("namespace") or "keycloak")
    ingress_class = _safe_str(ingress.get("class"))
    ingress_domain = _safe_str(ingress.get("domain"))
    ingress_secret = _safe_str(ingress.get("secret"))
    ingress_enabled = _boolish(ingress.get("enabled"))
    ingress_annotations = ingress.get("annotations") or {}
    if not isinstance(ingress_annotations, dict):
        ingress_annotations = {}
    gateway = environment.get("httpRoute") or {}
    route_enabled = _boolish(gateway.get("enabled"))
    route_timeouts = _http_route_timeouts(environment) if route_enabled else {}
    upstream_timeout = _safe_str((environment.get("oauth2Proxy") or {}).get("upstreamTimeout", "3600s"))
    permanent_access = ingress_enabled or route_enabled
    s3_enabled = _boolish(gateway.get("enableS3"))
    gateway_namespace = _safe_str(gateway.get("parentNamespace"))

    endpoint_env = {
        "name": "AWS_ENDPOINT_URL",
        "valueFrom": {
            "secretKeyRef": {
                "name": storage_secret_name,
                "key": "AWS_ENDPOINT_URL",
            }
        },
    }

    labels = {
        "app.kubernetes.io/name": "package-r",
        "app.kubernetes.io/instance": xr_name,
    }
    package_r_users = list(
        dict.fromkeys(
            [
                *([] if permanent_access else ["datalab"]),
                *[
                    _safe_str(user)
                    for user in (spec.get("users") or [])
                    if _safe_str(user)
                ],
            ]
        )
    )
    user_commands = "\n".join(
        " ".join(
            _shlex.quote(arg)
            for arg in ["/package-r", "users", "add", user, "", *write_permission_args]
        )
        for user in package_r_users
    )

    public_share_path = _shlex.quote(f"/{xr_name}/public")

    init_script = f"""set -eu

database=/state/package-r.db
work_database=/state/package-r.db.new

rm -f "$work_database"
export PACKAGE_R_DATABASE="$work_database"

/package-r config init \
  --address=0.0.0.0 \
  --port=8888 \
  --cors-allowed-origins='*' \
  --auth.method=proxy \
  --auth.header=X-Forwarded-Preferred-Username \
  --auth.mapper=

/package-r users add default ""
{user_commands}
/package-r shares add default public {public_share_path} \
  --password="" \
  --description="default public share" \
  --catalog-name=catalog.parquet

mv "$work_database" "$database"
"""

    deployment = _render_template(
        req,
        "data/deployment",
        runtime_namespace=runtime_namespace,
        labels=labels,
        storage_secret_checksum=storage_secret_checksum,
        package_r_image=package_r_image,
        init_script=init_script,
        containers=[
            _render_template(
                req,
                "data/package-r-container",
                package_r_image=package_r_image,
                endpoint_env=endpoint_env,
                storage_secret_name=storage_secret_name,
            )
        ]
        + (
            [
                _render_template(
                    req,
                    "data/oauth2-proxy-container",
                    oauth2_proxy_image=oauth2_proxy_image,
                    args=[
                        "--http-address=0.0.0.0:4180",
                        "--metrics-address=127.0.0.1:44180",
                        "--provider=keycloak-oidc",
                        f"--provider-display-name={realm} realm",
                        f"--client-id={xr_name}",
                        "--client-secret-file=/var/run/datalab/oauth2/client_secret",
                        "--cookie-secret-file=/var/run/datalab/oauth2/cookie_secret",
                        f"--oidc-issuer-url={issuer_url}",
                        "--skip-oidc-discovery=true",
                        f"--login-url={issuer_url}/protocol/openid-connect/auth",
                        f"--redeem-url={internal_iam_url}/protocol/openid-connect/token",
                        f"--oidc-jwks-url={internal_iam_url}/protocol/openid-connect/certs",
                        f"--profile-url={internal_iam_url}/protocol/openid-connect/userinfo",
                        "--insecure-oidc-skip-nonce=false",
                        "--scope=openid email profile",
                        "--code-challenge-method=S256",
                        f"--redirect-url=https://{xr_name}.{ingress_domain}/oauth2/callback",
                        "--upstream=http://127.0.0.1:8888/",
                        f"--upstream-timeout={upstream_timeout}",
                        "--email-domain=*",
                        f"--allowed-group={xr_name}",
                        "--reverse-proxy=true",
                        *[f"--trusted-proxy-ip={cidr}" for cidr in pod_cidrs],
                        f"--whitelist-domain={xr_name}.{ingress_domain}",
                        "--pass-basic-auth=false",
                        "--pass-access-token=false",
                        "--pass-authorization-header=false",
                        "--pass-user-headers=true",
                        "--skip-provider-button=true",
                        f"--cookie-name=__Host-{xr_name}",
                        "--cookie-secure=true",
                        "--cookie-httponly=true",
                        "--cookie-samesite=lax",
                        "--cookie-refresh=1h",
                        "--cookie-expire=8h",
                        "--cookie-csrf-per-request=true",
                        "--cookie-csrf-per-request-limit=5",
                        "--skip-auth-route=GET=^/api/public(/|$)",
                        "--skip-auth-route=HEAD=^/api/public(/|$)",
                        "--skip-auth-route=OPTIONS=^/api/public(/|$)",
                        "--skip-auth-route=GET=^/public(/|$)",
                        "--skip-auth-route=HEAD=^/public(/|$)",
                        "--skip-auth-route=OPTIONS=^/public(/|$)",
                        "--skip-auth-route=GET=^/share(/|$)",
                        "--skip-auth-route=HEAD=^/share(/|$)",
                        "--skip-auth-route=OPTIONS=^/share(/|$)",
                        "--skip-auth-route=GET=^/static(/|$)",
                        "--skip-auth-route=HEAD=^/static(/|$)",
                        "--skip-auth-route=OPTIONS=^/static(/|$)",
                        "--silence-ping-logging=true",
                    ],
                )
            ]
            if permanent_access
            else []
        ),
    )

    storage_volume = {
        "name": "storage-credentials",
        "secret": {
            "secretName": storage_secret_name,
            "defaultMode": 0o440,
            "items": [{"key": "aws-credentials", "path": "aws-credentials"}],
        },
    }
    deployment["spec"]["template"]["spec"]["volumes"].append(storage_volume)

    oauth_volume = {
        "name": "oauth2-credentials",
        "secret": {
            "secretName": f"{xr_name}-oauth2-client",
            "defaultMode": 0o440,
            "items": [
                {"key": key, "path": key} for key in ("client_secret", "cookie_secret")
            ],
        },
    }
    oauth_cookie_checksum = ""
    if permanent_access:
        deployment["spec"]["template"]["spec"]["volumes"].append(oauth_volume)
        oauth_resource = rsp.desired.resources.get(f"oauth2-client-secret-{xr_name}")
        oauth_object = _to_dict(oauth_resource.resource) if oauth_resource else {}
        oauth_manifest = (
            (oauth_object.get("spec") or {}).get("forProvider") or {}
        ).get("manifest") or {}
        cookie_secret = _b64get_any(
            oauth_manifest.get("data") or {}, ["cookie_secret"]
        )
        if cookie_secret:
            # The cookie cipher is built at startup, even when a Secret file is used.
            oauth_cookie_checksum = _hashlib.sha256(
                cookie_secret.encode("utf-8")
            ).hexdigest()
            deployment["spec"]["template"]["metadata"]["annotations"][
                "datalabs.versioneer.at/oauth2-cookie-checksum"
            ] = oauth_cookie_checksum

    service = _render_template(
        req,
        "data/service",
        runtime_namespace=runtime_namespace,
        labels=labels,
        ports=(
            [
                {
                    "name": "http",
                    "port": 8888,
                    "targetPort": "package-r",
                    "protocol": "TCP",
                }
            ]
            if not permanent_access
            else []
        )
        + (
            [
                {
                    "name": "auth-proxy",
                    "port": 4180,
                    "targetPort": "auth-proxy",
                    "protocol": "TCP",
                }
            ]
            if permanent_access
            else []
        ),
    )

    network_policy = _render_template(
        req,
        "data/network-policy",
        runtime_namespace=runtime_namespace,
        labels=labels,
        ingress_rules=(
            [
                {
                    "from": [
                        {
                            "podSelector": {
                                "matchLabels": {}
                            }
                        }
                    ],
                    "ports": [{"protocol": "TCP", "port": 8888}],
                }
            ]
            if not permanent_access
            else []
        )
        + (
            [
                {
                    "ports": [{"protocol": "TCP", "port": 4180}],
                }
            ]
            if permanent_access
            else []
        ),
        egress_rules=[
            {
                "to": [
                    {
                        "namespaceSelector": {
                            "matchLabels": {
                                "kubernetes.io/metadata.name": iam_namespace,
                            }
                        }
                    }
                ],
                "ports": [{"protocol": "TCP", "port": 8080}],
            }
        ]
        if permanent_access
        else [],
    )

    permanent_ingress = _render_template(
        req,
        "data/permanent-ingress",
        runtime_namespace=runtime_namespace,
        labels=labels,
        ingress_annotations=ingress_annotations,
        ingress_class=ingress_class,
        hostname=f"{xr_name}.{ingress_domain}",
        ingress_secret=ingress_secret,
    )

    s3_labels = {
        "app.kubernetes.io/name": "data-s3",
        "app.kubernetes.io/instance": xr_name,
    }
    s3_deployment = _render_template(
        req,
        "data/s3-deployment",
        rclone_image=rclone_image,
        runtime_namespace=runtime_namespace,
        s3_labels=s3_labels,
        storage_secret_checksum=storage_secret_checksum,
        auth_key_arg=f"--auth-key={xr_name},{xr_name}",
        s3_environment=[
            {"name": "RCLONE_CONFIG_UPSTREAM_TYPE", "value": "s3"},
            {"name": "RCLONE_CONFIG_UPSTREAM_ENV_AUTH", "value": "true"},
            {
                "name": "AWS_SHARED_CREDENTIALS_FILE",
                "value": "/var/run/datalab/storage/aws-credentials",
            },
            {
                "name": "RCLONE_CONFIG_UPSTREAM_PROVIDER",
                "value": _safe_str(storage.get("provider") or "Other"),
            },
            {
                "name": "RCLONE_CONFIG_UPSTREAM_FORCE_PATH_STYLE",
                "value": str(storage.get("forcePathStyle", "true")).lower(),
            },
            *[
                {
                    "name": name,
                    "valueFrom": {
                        "secretKeyRef": {
                            "name": storage_secret_name,
                            "key": key,
                            **(
                                {"optional": True} if key == "AWS_SESSION_TOKEN" else {}
                            ),
                        }
                    },
                }
                for name, key in (
                    ("RCLONE_CONFIG_UPSTREAM_ENDPOINT", "AWS_ENDPOINT_URL"),
                    ("RCLONE_CONFIG_UPSTREAM_REGION", "AWS_REGION"),
                )
            ],
        ],
        access_key_arg=f"--s3-access-key-id={xr_name}",
        secret_key_arg=f"--s3-secret-access-key={xr_name}",
    )
    s3_deployment["spec"]["template"]["spec"]["volumes"].append(
        _copy.deepcopy(storage_volume)
    )

    s3_service = _render_template(
        req,
        "data/s3-service",
        runtime_namespace=runtime_namespace,
        s3_labels=s3_labels,
    )
    s3_network_policy = _render_template(
        req,
        "data/s3-network-policy",
        runtime_namespace=runtime_namespace,
        s3_labels=s3_labels,
        ingress_rules=[
            {
                "from": [
                    {
                        "namespaceSelector": {
                            "matchLabels": {
                                "kubernetes.io/metadata.name": gateway_namespace,
                            }
                        }
                    }
                ],
                "ports": [{"protocol": "TCP", "port": 8080}],
            }
        ]
        if permanent_access
        else [],
    )
    if s3_enabled:
        s3_network_policy["spec"]["policyTypes"].append("Egress")
        s3_network_policy["spec"]["egress"] = _copy.deepcopy(
            network_policy["spec"]["egress"]
        )
        auth_proxy = _copy.deepcopy(
            next(
                container
                for container in deployment["spec"]["template"]["spec"]["containers"]
                if container["name"] == "oauth2-proxy"
            )
        )
        auth_proxy["args"] = [
            arg
            for arg in auth_proxy["args"]
            if not arg.startswith(
                (
                    "--upstream=",
                    "--allowed-group=",
                    "--skip-auth-route=",
                    "--http-address=",
                )
            )
        ] + [
            "--http-address=127.0.0.1:4180",
            "--upstream=static://202",
            "--skip-jwt-bearer-tokens=true",
            "--bearer-token-login-fallback=false",
            "--insecure-oidc-allow-unverified-email=true",
            *[
                f"--allowed-role={xr_name}:{role}"
                for role in ("ws_access", "ws_admin", "ws_api")
            ],
            "--request-logging=false",
            "--auth-logging=false",
        ]
        for key in ("readinessProbe", "livenessProbe", "ports"):
            auth_proxy.pop(key, None)
        # Keep both original SigV4 headers and the token unchanged for rclone.
        gateway_config = "\n".join(
            [
                "pid /tmp/nginx.pid;",
                "error_log /dev/stderr warn;",
                "events { worker_connections 1024; }",
                "http {",
                "  access_log off;",
                "  client_body_temp_path /tmp/body; proxy_temp_path /tmp/proxy;",
                "  fastcgi_temp_path /tmp/fastcgi; uwsgi_temp_path /tmp/uwsgi; scgi_temp_path /tmp/scgi;",
                "  map $http_authorization $tenant_valid {",
                "    default 0;",
                f"    ~^AWS4-HMAC-SHA256\\s+Credential={xr_name}/ 1;",
                "  }",
                "  server {",
                "    listen 8080;",
                "    location = /_ready { proxy_pass http://127.0.0.1:4180/ready; }",
                "    location / {",
                "      if ($tenant_valid = 0) { return 403; }",
                '      if ($http_x_amz_security_token = "") { return 403; }',
                "      limit_except GET { deny all; }",
                "      auth_request /_s3_auth;",
                "      proxy_set_header Host $http_host;",
                "      proxy_buffering off; proxy_read_timeout 3600s;",
                "      proxy_pass http://127.0.0.1:8081;",
                "    }",
                "    location = /_s3_auth {",
                "      internal; proxy_pass_request_body off;",
                '      proxy_set_header Content-Length "";',
                '      proxy_set_header Cookie "";',
                '      proxy_set_header Authorization "Bearer $http_x_amz_security_token";',
                "      proxy_pass http://127.0.0.1:4180/oauth2/auth?;",
                "    }",
                "  }",
                "}",
                "",
            ]
        )
        s3_config = _render_template(
            req,
            "data/s3-config",
            runtime_namespace=runtime_namespace,
            gateway_config=gateway_config,
        )
        pod = s3_deployment["spec"]["template"]
        pod["spec"]["volumes"].append(_copy.deepcopy(oauth_volume))
        if oauth_cookie_checksum:
            pod["metadata"]["annotations"][
                "datalabs.versioneer.at/oauth2-cookie-checksum"
            ] = oauth_cookie_checksum
        pod["metadata"]["annotations"][
            "datalabs.versioneer.at/gateway-config-checksum"
        ] = _hashlib.sha256(gateway_config.encode()).hexdigest()
        pod["spec"]["volumes"].append(
            {"name": "gateway-config", "configMap": {"name": "data-s3"}}
        )
        pod["spec"]["containers"].extend(
            [
                auth_proxy,
                _render_template(
                    req,
                    "data/gateway-container",
                ),
            ]
        )

    data_route = _render_template(
        req,
        "data/data-route",
        runtime_namespace=runtime_namespace,
        gateway_name=_safe_str(gateway.get("parentName")),
        gateway_namespace=gateway_namespace,
        gateway_section=_safe_str(gateway.get("sectionName")),
        hostname=f"{xr_name}.{ingress_domain}",
        route_rules=(
            [
                {
                    "matches": [
                        {
                            "headers": [
                                {
                                    "name": "User-Agent",
                                    "type": "RegularExpression",
                                    "value": "^aws-cli/.*",
                                }
                            ]
                        },
                        {
                            "headers": [
                                {
                                    "name": "Authorization",
                                    "type": "RegularExpression",
                                    "value": "^AWS4-HMAC-SHA256 .*",
                                }
                            ]
                        },
                        {
                            "queryParams": [
                                {
                                    "name": "X-Amz-Algorithm",
                                    "value": "AWS4-HMAC-SHA256",
                                }
                            ]
                        },
                    ],
                    "backendRefs": [{"name": "data-s3", "port": 8080}],
                    "timeouts": route_timeouts,
                }
            ]
            if s3_enabled
            else []
        )
        + [
            {
                "backendRefs": [{"name": "package-r", "port": 4180}],
                "timeouts": route_timeouts,
            }
        ],
    )
    data_redirect = _render_template(
        req,
        "data/data-redirect",
        runtime_namespace=runtime_namespace,
        gateway_name=_safe_str(gateway.get("parentName")),
        gateway_namespace=gateway_namespace,
        gateway_section=_safe_str(gateway.get("httpSectionName")),
        hostname=f"{xr_name}.{ingress_domain}",
    )

    dns_targets = [
        {
            "namespaceSelector": {
                "matchLabels": {
                    "kubernetes.io/metadata.name": "kube-system",
                }
            }
        }
    ]
    if service_cidr:
        dns_targets.append({"ipBlock": {"cidr": service_cidr}})

    dns_network_policy = _render_template(
        req,
        "data/dns-network-policy",
        runtime_namespace=runtime_namespace,
        labels=labels,
        dns_targets=dns_targets,
    )

    def emit(key, manifest, readiness=None):
        body = _render_template(
            req,
            "common/object",
            key=key,
            xr_namespace=xr_namespace,
            manifest=manifest,
            readiness=readiness or {"policy": "SuccessfulCreate"},
        )
        rsp.desired.resources[key].resource.update(body)

    emit(
        f"data-deployment-{xr_name}",
        deployment,
        readiness={
            "policy": "DeriveFromCelQuery",
            "celQuery": "has(object.status) && has(object.status.observedGeneration) && object.status.observedGeneration >= object.metadata.generation && has(object.status.availableReplicas) && object.status.availableReplicas >= 1",
        },
    )
    emit(f"data-service-{xr_name}", service)
    emit(f"data-networkpolicy-{xr_name}", network_policy)
    if permanent_access:
        if route_enabled:
            route_readiness = {
                "policy": "DeriveFromCelQuery",
                "celQuery": (
                    "has(object.status) && has(object.status.parents) && "
                    f"object.status.parents.exists(p, p.parentRef.name == {_json.dumps(_safe_str(gateway.get('parentName')))} && "
                    f"has(p.parentRef.namespace) && p.parentRef.namespace == {_json.dumps(gateway_namespace)} && "
                    "has(p.parentRef.sectionName) && p.parentRef.sectionName == object.spec.parentRefs[0].sectionName && "
                    "has(p.conditions) && "
                    "p.conditions.exists(c, c.type == 'Accepted' && c.status == 'True' && "
                    "c.observedGeneration == object.metadata.generation) && "
                    "p.conditions.exists(c, c.type == 'ResolvedRefs' && c.status == 'True' && "
                    "c.observedGeneration == object.metadata.generation))"
                ),
            }
            emit(f"data-route-{xr_name}", data_route, readiness=route_readiness)
            emit(f"data-redirect-{xr_name}", data_redirect, readiness=route_readiness)
        else:
            emit(f"data-ingress-{xr_name}", permanent_ingress)
    if s3_enabled:
        emit(f"data-s3-config-{xr_name}", s3_config)
        emit(
            f"data-s3-deployment-{xr_name}",
            s3_deployment,
            readiness={
                "policy": "DeriveFromCelQuery",
                "celQuery": "has(object.status) && has(object.status.observedGeneration) && object.status.observedGeneration >= object.metadata.generation && has(object.status.availableReplicas) && object.status.availableReplicas >= 1",
            },
        )
        emit(f"data-s3-service-{xr_name}", s3_service)
        emit(f"data-s3-networkpolicy-{xr_name}", s3_network_policy)
    if "allow-dns-egress" not in excluded_network_policies:
        emit(f"data-dns-networkpolicy-{xr_name}", dns_network_policy)
