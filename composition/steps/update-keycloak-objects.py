# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

from crossplane.function.proto.v1 import run_function_pb2 as fnv1

from composition.helpers import (
    _boolish,
    _safe_str,
    _session_name,
    _to_dict,
)
from composition.render import _render_template


def _distinct(seq):
    return list(dict.fromkeys(seq))


def _workspace_redirect_uris(xr_name, domain, session_names):
    uris = [f"https://{xr_name}.{domain}/*"]
    for sid in session_names:
        session_host = f"{xr_name}-{sid}"
        uris.extend(
            [
                f"https://{session_host}.{domain}/*",
                f"https://editor-{session_host}.{domain}/*",
                f"https://{session_host}-editor.{domain}/*",
                f"https://data-{session_host}.{domain}/*",
                f"https://{session_host}-data.{domain}/*",
            ]
        )
    uris.append("http://localhost:*")
    return _distinct(uris)


def compose(req: fnv1.RunFunctionRequest, rsp: fnv1.RunFunctionResponse):
    xr = _to_dict(req.observed.composite.resource)
    metadata = xr.get("metadata", {}) or {}
    spec = xr.get("spec", {}) or {}

    xr_name = metadata.get("name")
    xr_namespace = metadata.get("namespace") or "default"

    context = _to_dict(req.context)
    environment = context.get("apiextensions.crossplane.io/environment", {}) or {}
    iam_env = environment.get("iam") or {}
    ingress_env = environment.get("ingress") or {}
    realm = iam_env.get("realm", "default")
    extra_audiences_raw = iam_env.get("extraAudiences")
    if isinstance(extra_audiences_raw, str):
        extra_audiences_raw = [extra_audiences_raw]
    elif not isinstance(extra_audiences_raw, list):
        extra_audiences_raw = []
    extra_audiences = _distinct(
        [_safe_str(audience) for audience in extra_audiences_raw if _safe_str(audience)]
    )
    data_enabled = ((environment.get("defaults") or {}).get("data") or {}).get(
        "enabled", True
    )
    s3_enabled = (environment.get("httpRoute") or {}).get("enableS3", False)
    if (data_enabled is None or _boolish(data_enabled)) and _boolish(s3_enabled):
        extra_audiences = _distinct([*extra_audiences, xr_name])
    domain = ingress_env.get("domain", "default")
    url = f"https://{xr_name}.{domain}"
    session_names = [
        _session_name(session)
        for session in (spec.get("sessions") or [])
        if _session_name(session)
    ]
    redirect_uris = _workspace_redirect_uris(xr_name, domain, session_names)

    def put(key_base, body_base, name_override=xr_name):
        key = f"{key_base}-{name_override}"
        body = body_base.copy()
        md = body.setdefault("metadata", {})
        md.setdefault("name", name_override)
        md.setdefault("namespace", xr_namespace)
        ann = md.setdefault("annotations", {})
        ann["crossplane.io/composition-resource-name"] = key
        rsp.desired.resources[key].resource.update(body)

    put(
        "keycloak-group",
        _render_template(
            req,
            "keycloak/users-group",
            xr_name=xr_name,
            realm=realm,
        ),
    )

    put(
        "keycloak-group-admin",
        _render_template(
            req,
            "keycloak/admins-group",
            display_name=f"{xr_name}-admin",
            realm=realm,
        ),
        f"{xr_name}-admin",
    )

    put(
        "keycloak-mapper",
        _render_template(
            req,
            "keycloak/group-membership-mapper",
            xr_name=xr_name,
            realm=realm,
        ),
    )

    put(
        "keycloak-client",
        _render_template(
            req,
            "keycloak/client",
            xr_name=xr_name,
            url=url,
            redirect_uris=redirect_uris,
            realm=realm,
            connection_secret_name=f"{xr_name}-oauth-client",
        ),
    )

    put(
        "keycloak-role-user",
        _render_template(
            req,
            "keycloak/access-role",
            xr_name=xr_name,
            realm=realm,
        ),
        f"{xr_name}-ws-access",
    )

    put(
        "keycloak-role-admin",
        _render_template(
            req,
            "keycloak/admin-role",
            xr_name=xr_name,
            realm=realm,
        ),
        f"{xr_name}-ws-admin",
    )

    put(
        "keycloak-role-api",
        _render_template(
            req,
            "keycloak/api-role",
            xr_name=xr_name,
            realm=realm,
        ),
        f"{xr_name}-ws-api",
    )

    def put_keycloak_role_mapper(key_base, role_name_override):
        put(
            key_base,
            _render_template(
                req,
                "keycloak/role-scope-mapper",
                realm=realm,
                xr_name=xr_name,
                role_name_override=role_name_override,
            ),
            role_name_override,
        )

    put_keycloak_role_mapper("keycloak-role-mapper-user", f"{xr_name}-ws-access")
    put_keycloak_role_mapper("keycloak-role-mapper-admin", f"{xr_name}-ws-admin")
    put_keycloak_role_mapper("keycloak-role-mapper-api", f"{xr_name}-ws-api")

    for audience in extra_audiences:
        audience_name = (
            "".join(
                [char.lower() if char.isalnum() else "-" for char in audience]
            ).strip("-")
            or "extra"
        )
        audience_name = (
            "-".join([part for part in audience_name.split("-") if part])[:48].strip(
                "-"
            )
            or "extra"
        )
        key_base = f"keycloak-extra-audience-{audience_name}"
        put(
            key_base,
            _render_template(
                req,
                "keycloak/audience-mapper",
                realm=realm,
                xr_name=xr_name,
                display_name=f"{audience_name}-audience",
                audience=audience,
            ),
            f"{xr_name}-{audience_name}-audience",
        )

    put(
        "keycloak-roles-user",
        _render_template(
            req,
            "keycloak/user-group-roles",
            realm=realm,
            xr_name=xr_name,
            role_name=f"{xr_name}-ws-access",
        ),
    )

    put(
        "keycloak-roles-admin",
        _render_template(
            req,
            "keycloak/admin-group-roles",
            realm=realm,
            group_name=f"{xr_name}-admin",
            role_name=f"{xr_name}-ws-admin",
        ),
        f"{xr_name}-admin",
    )

    # Keep the resolved identity in desired state. Multiple provider
    # reference updates can otherwise remove an earlier resolved field.
    observed_client = (getattr(req.observed, "resources", {}) or {}).get(
        f"keycloak-client-{xr_name}"
    )
    client_state = _to_dict(observed_client.resource) if observed_client else {}
    client_identity = (client_state.get("status") or {}).get("atProvider") or {}
    service_account_inputs = {}
    if _safe_str(client_identity.get("id")) and _safe_str(
        client_identity.get("serviceAccountUserId")
    ):
        service_account_inputs = {
            "clientId": client_identity["id"],
            "serviceAccountUserId": client_identity["serviceAccountUserId"],
            "role": "ws_api",
        }

    put(
        "keycloak-service-account-role-api",
        _render_template(
            req,
            "keycloak/service-account-role",
            role_binding={
                "realmId": realm,
                "clientIdRef": {"name": xr_name, "policy": {"resolution": "Required"}},
                "roleRef": {
                    "name": f"{xr_name}-ws-api",
                    "policy": {"resolution": "Required"},
                },
                "serviceAccountUserClientIdRef": {
                    "name": xr_name,
                    "policy": {"resolution": "Required"},
                },
                **service_account_inputs,
            },
        ),
        f"{xr_name}-ws-api",
    )

    users = list(spec.get("users", []) or [])
    userOverrides = spec.get("userOverrides", {}) or {}

    role_admins = [
        u
        for u in users
        if str(((userOverrides.get(u) or {}).get("role") or "")).strip() == "admin"
    ]

    admins = _distinct((users[0:1] or []) + role_admins)

    put(
        "keycloak-memberships-users",
        _render_template(
            req,
            "keycloak/user-memberships",
            xr_name=xr_name,
            realm=realm,
            users=users,
        ),
    )

    put(
        "keycloak-memberships-admins",
        _render_template(
            req,
            "keycloak/admin-memberships",
            group_name=f"{xr_name}-admin",
            realm=realm,
            admins=admins,
        ),
        f"{xr_name}-admin",
    )
