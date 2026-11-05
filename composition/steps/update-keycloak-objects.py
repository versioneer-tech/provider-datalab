# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

import json

from crossplane.function.proto.v1 import run_function_pb2 as fnv1

from composition.helpers import (
    _safe_str,
    _resource_name,
    _session_name,
    _to_dict,
    _vcluster_groups,
    _vcluster_exchange_groups,
    _vcluster_profile,
    _vcluster_role,
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


def _security_ready(req, resources):
    def contains(actual, expected):
        if isinstance(expected, dict):
            return isinstance(actual, dict) and all(
                key in actual and contains(actual[key], value)
                for key, value in expected.items()
            )
        if isinstance(expected, list):
            return isinstance(actual, list) and len(actual) == len(expected) and all(
                any(contains(item, value) for item in actual) for value in expected
            )
        return actual == expected

    for key, desired in resources.items():
        observed = req.observed.resources.get(key)
        state = _to_dict(observed.resource) if observed else {}
        conditions = {
            condition.get("type"): condition.get("status")
            for condition in (state.get("status") or {}).get("conditions") or []
        }
        if (state.get("metadata") or {}).get("deletionTimestamp") or any(
            conditions.get(name) != "True" for name in ("Ready", "Synced")
        ) or not contains(state.get("spec") or {}, desired["spec"]):
            return False
    return True


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
    extra_audiences = _distinct([
        xr_name,
        *[_safe_str(audience) for audience in extra_audiences_raw if _safe_str(audience)],
    ])
    domain = ingress_env.get("domain", "default")
    url = f"https://{xr_name}.{domain}"
    session_names = [
        _session_name(session)
        for session in (spec.get("sessions") or [])
        if _session_name(session)
    ]
    redirect_uris = _workspace_redirect_uris(xr_name, domain, session_names)

    security_resources = {}

    def put(key_base, body_base, name_override=xr_name):
        key = f"{key_base}-{name_override}"
        body = body_base.copy()
        md = body.setdefault("metadata", {})
        md.setdefault("name", name_override)
        md.setdefault("namespace", xr_namespace)
        ann = md.setdefault("annotations", {})
        ann["crossplane.io/composition-resource-name"] = key
        rsp.desired.resources[key].resource.update(body)
        if body["kind"] in {
            "ClientScope", "ClientDefaultScopes", "ClientOptionalScopes",
            "RoleMapper", "ProtocolMapper", "ClientPolicyProfile", "ClientPolicyProfilePolicy",
        }:
            security_resources[key] = body

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
            exchange_enabled=False,
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

    def put_keycloak_role_mapper(key_base, role_name_override, name_override=None):
        put(
            key_base,
            _render_template(
                req,
                "keycloak/role-scope-mapper",
                realm=realm,
                xr_name=xr_name,
                role_name_override=role_name_override,
            ),
            name_override or role_name_override,
        )

    put_keycloak_role_mapper("keycloak-role-mapper-api", f"{xr_name}-ws-api")

    interactive_scope = f"{xr_name}:interactive"
    interactive_resource = _resource_name(xr_name, "interactive")
    policy_name = _resource_name(xr_name, "reject-interactive-exchange")
    put("keycloak-exchange-policy-profile", _render_template(
        req, "keycloak/exchange-policy-profile", realm=realm, policy_name=policy_name,
    ), policy_name)
    put("keycloak-exchange-policy", _render_template(
        req, "keycloak/exchange-policy", realm=realm, policy_name=policy_name,
        interactive_scopes_json=json.dumps([interactive_scope]),
    ), policy_name)

    def put_scope(name, resource, roles):
        put("keycloak-optional-scope", _render_template(
            req, "keycloak/client-scope", realm=realm, scope_name=name,
        ), resource)
        for role in roles:
            put("keycloak-optional-role", _render_template(
                req, "keycloak/optional-role-scope-mapper", realm=realm,
                scope_resource=resource, role_resource=role,
            ), _resource_name(resource, role))

    instances = spec.get("vclusters") or {}
    additional_profiles = [
        (instance, group["name"])
        for instance, config in sorted(instances.items())
        for group in _vcluster_exchange_groups(config)
    ]
    additional_roles = [
        _vcluster_profile(xr_name, instance, group)
        for instance, group in additional_profiles
    ]
    admin_roles = [
        _vcluster_profile(xr_name, instance, "cluster-admin")
        for instance in sorted(instances)
    ]
    put_scope(interactive_scope, interactive_resource, [
        f"{xr_name}-ws-access", f"{xr_name}-ws-admin", *admin_roles,
    ])
    optional_scopes = [interactive_scope]
    for (instance, group), role in zip(additional_profiles, additional_roles):
        scope = f"{xr_name}:vclusters_{instance}_{group}"
        put_scope(scope, _resource_name(role, "scope"), [role])
        optional_scopes.append(scope)

    for kind, field, names in (
        ("ClientDefaultScopes", "defaultScopes", ["basic", "profile", "email"]),
        ("ClientOptionalScopes", "optionalScopes", optional_scopes),
    ):
        put(f"keycloak-{field}", _render_template(
            req, "keycloak/client-scopes", scope_kind=kind,
            scope_binding={
                "realmId": realm,
                "clientIdRef": {"name": xr_name, "policy": {"resolution": "Required"}},
                field: names,
            },
        ))
    put("keycloak-client-roles", _render_template(
        req, "keycloak/client-roles-mapper", realm=realm, xr_name=xr_name,
        claim_name=f"resource_access.{xr_name}.roles",
    ))

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
            role_refs=[
                {"name": role, "policy": {"resolution": "Required", "resolve": "Always"}}
                for role in [
                    f"{xr_name}-ws-access",
                    f"{xr_name}-ws-api",
                    *additional_roles,
                ]
            ],
        ),
    )

    put(
        "keycloak-roles-admin",
        _render_template(
            req,
            "keycloak/admin-group-roles",
            realm=realm,
            group_name=f"{xr_name}-admin",
            role_refs=[
                {"name": role, "policy": {"resolution": "Required", "resolve": "Always"}}
                for role in [f"{xr_name}-ws-admin", f"{xr_name}-ws-api", *admin_roles, *additional_roles]
            ],
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

    for instance, config in sorted((spec.get("vclusters") or {}).items()):
        for group in _vcluster_groups(config):
            profile = _vcluster_profile(xr_name, instance, group["name"])
            role_name = _vcluster_role(instance, group["name"])
            put(
                "keycloak-vcluster-role",
                _render_template(
                    req,
                    "vcluster/identity-role",
                    realm=realm,
                    role_name=role_name,
                    xr_name=xr_name,
                ),
                profile,
            )

    users = list(spec.get("users", []) or [])
    userOverrides = spec.get("userOverrides", {}) or {}

    role_admins = [
        u
        for u in users
        if str(((userOverrides.get(u) or {}).get("role") or "")).strip() == "admin"
    ]

    admins = _distinct((users[0:1] or []) + role_admins)

    # The provider rejects an empty member list. Delete its membership resource to clear the group.
    if users:
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

    if admins:
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

    # Wait for scope restrictions and deletion of old broad mappings before exchange.
    stale_security = any(
        key not in security_resources
        and _to_dict(observed.resource).get("kind") in {"RoleMapper", "ProtocolMapper", "ClientScope"}
        for key, observed in req.observed.resources.items()
    )
    rsp.desired.resources[f"keycloak-client-{xr_name}"].resource["spec"]["forProvider"][
        "standardTokenExchangeEnabled"
    ] = not stale_security and _security_ready(req, security_resources)
