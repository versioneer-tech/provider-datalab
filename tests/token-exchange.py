# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Check the managed boundaries for user-token exchange."""

from copy import deepcopy
import json

from render import arguments, environment, render


def main():
    args, env = arguments(), environment()
    source = {
        "apiVersion": "pkg.internal/v1beta2", "kind": "Datalab",
        "metadata": {"name": "s-joe", "namespace": "workspace"},
        "spec": {"users": ["joe", "jane", "john"], "userOverrides": {"john": {"role": "admin"}},
                 "vclusters": {"vc0": {"groups": [{"name": "namespace-demo", "namespace": "demo", "role": "edit"}]},
                               "vc1": {}}},
    }
    initial = render(args, env, source, [])

    def params(resources, kind):
        return [body["spec"]["forProvider"] for body in resources.values() if body.get("kind") == kind]

    roles = {body["metadata"]["name"]: body["spec"]["forProvider"]["name"]
             for body in initial.values() if body.get("kind") == "Role"}

    def grants(resources, group):
        binding = next(item for item in params(resources, "Roles") if item["groupIdRef"]["name"] == group)
        assert binding["exhaustive"]
        return {roles[ref["name"]] for ref in binding["roleIdsRefs"]}

    assert grants(initial, "s-joe") == {"ws_access", "ws_api", "vcluster_vc0_namespace-demo"}
    assert grants(initial, "s-joe-admin") == {
        "ws_admin", "ws_api", "vcluster_vc0_namespace-demo",
        "vcluster_vc0_cluster-admin", "vcluster_vc1_cluster-admin",
    }
    memberships = {item["groupIdRef"]["name"]: item["members"] for item in params(initial, "Memberships")}
    assert memberships == {"s-joe": ["joe", "jane", "john"], "s-joe-admin": ["joe", "john"]}
    client, = params(initial, "Client")
    assert client["clientId"] == "s-joe" and client["accessType"] == "CONFIDENTIAL"
    assert client["serviceAccountsEnabled"] and not client["fullScopeAllowed"]
    assert not client["oauth2DeviceAuthorizationGrantEnabled"] and not client["standardTokenExchangeEnabled"]
    assert params(initial, "ClientDefaultScopes")[0]["defaultScopes"] == ["basic", "profile", "email"]
    scopes = {body["metadata"]["name"]: body["spec"]["forProvider"]["name"]
              for body in initial.values() if body.get("kind") == "ClientScope"}
    assert set(scopes.values()) == {"s-joe:interactive", "s-joe:vclusters_vc0_namespace-demo"}
    assert all(item["includeInTokenScope"] for item in params(initial, "ClientScope"))
    assert set(params(initial, "ClientOptionalScopes")[0]["optionalScopes"]) == set(scopes.values())
    dedicated = [item for item in params(initial, "RoleMapper") if "clientIdRef" in item]
    assert len(dedicated) == 1 and roles[dedicated[0]["roleIdRef"]["name"]] == "ws_api"
    optional = {}
    for item in params(initial, "RoleMapper"):
        if "clientScopeIdRef" in item:
            optional.setdefault(scopes[item["clientScopeIdRef"]["name"]], set()).add(roles[item["roleIdRef"]["name"]])
    assert optional == {
        "s-joe:vclusters_vc0_namespace-demo": {"vcluster_vc0_namespace-demo"},
        "s-joe:interactive": {"ws_access", "ws_admin", "vcluster_vc0_cluster-admin", "vcluster_vc1_cluster-admin"},
    }
    policy, = params(initial, "ClientPolicyProfilePolicy")
    conditions = {item["name"]: item["configuration"] for item in policy["condition"]}
    assert policy["enabled"]
    assert json.loads(conditions["grant-type"]["grant_types"]) == ["urn:ietf:params:oauth:grant-type:token-exchange"]
    assert conditions["client-scopes"]["type"] == "Any"
    assert json.loads(conditions["client-scopes"]["scopes"]) == ["s-joe:interactive"]
    assert params(initial, "ClientPolicyProfile")[0]["executor"] == [{"name": "reject-request"}]
    mappers = params(initial, "ProtocolMapper")
    assert {item["config"]["included.client.audience"] for item in mappers
            if item["protocolMapper"] == "oidc-audience-mapper"} == {"s-joe"}
    role_mapper, = [item for item in mappers if item["protocolMapper"] == "oidc-usermodel-client-role-mapper"]
    assert role_mapper["config"]["usermodel.clientRoleMapping.clientId"] == "s-joe"
    assert role_mapper["config"]["claim.name"] == "resource_access.s-joe.roles"
    assert not any(item.get("kind") in {"Realm", "DefaultClientScopes", "OptionalClientScopes"} for item in initial.values())
    assert all(item.get("clientIdRef", {}).get("name") == "s-joe" for item in mappers)
    account, = params(initial, "ClientServiceAccountRole")
    assert roles[account["roleRef"]["name"]] == "ws_api"
    print("PASS exact group grants, scope boundaries, policy, audiences, and unchanged workspace account")

    configured_env = deepcopy(env)
    configured_env["data"]["iam"]["extraAudiences"] = ["test-service"]
    configured = render(args, configured_env, source, [])
    assert {item["config"]["included.client.audience"] for item in params(configured, "ProtocolMapper")
            if item["protocolMapper"] == "oidc-audience-mapper"} == {"s-joe", "test-service"}
    assert len(params(configured, "Client")) == 1
    added_mappers = set(configured) - set(initial)
    audience_removed = render(args, env, source, list(configured.values()))
    assert added_mappers and added_mappers.isdisjoint(audience_removed)
    assert {item["config"]["included.client.audience"] for item in params(audience_removed, "ProtocolMapper")
            if item["protocolMapper"] == "oidc-audience-mapper"} == {"s-joe"}
    print("PASS standalone workspace audience and configured extra audience addition and removal")

    observed = deepcopy(list(initial.values()))
    for body in observed:
        body["status"] = {"conditions": [{"type": name, "status": "True"} for name in ("Ready", "Synced")]}
    reconciled = render(args, env, source, observed)
    assert params(reconciled, "Client")[0]["standardTokenExchangeEnabled"]
    stale = deepcopy(next(body for body in observed if body["kind"] == "RoleMapper" and "clientIdRef" in body["spec"]["forProvider"]))
    stale["metadata"]["annotations"]["crossplane.io/composition-resource-name"] = "keycloak-role-mapper-user-s-joe-ws-access"
    assert not params(render(args, env, source, [*observed, stale]), "Client")[0]["standardTokenExchangeEnabled"]
    pending = deepcopy(observed)
    next(body for body in pending if body["kind"] == "ClientPolicyProfilePolicy")["status"]["conditions"][0]["status"] = "False"
    assert not params(render(args, env, source, pending), "Client")[0]["standardTokenExchangeEnabled"]
    print("PASS exchange waits for reconciled restrictions and removal of old broad mappings")

    renamed = deepcopy(source)
    renamed["spec"]["vclusters"]["vc0"]["groups"][0]["name"] = "renamed"
    changed = render(args, env, renamed, observed)
    old_keys = {key for key, body in initial.items() if body["kind"] in {"ClientScope", "RoleMapper"}
                and "namespace-demo" in json.dumps(body)}
    assert old_keys and old_keys.isdisjoint(changed)
    assert set(params(changed, "ClientOptionalScopes")[0]["optionalScopes"]) == {"s-joe:interactive", "s-joe:vclusters_vc0_renamed"}
    assert not params(changed, "Client")[0]["standardTokenExchangeEnabled"]
    empty = deepcopy(source)
    empty["spec"]["vclusters"] = {"vc1": {"groups": [{"name": "cluster-admin", "namespace": "*", "role": "cluster-admin"}]}}
    removed = render(args, env, empty, observed)
    assert set(params(removed, "ClientOptionalScopes")[0]["optionalScopes"]) == {"s-joe:interactive"}
    assert old_keys.isdisjoint(removed)
    assert grants(removed, "s-joe") == {"ws_access", "ws_api"}
    assert grants(removed, "s-joe-admin") == {"ws_admin", "ws_api", "vcluster_vc1_cluster-admin"}
    print("PASS profile rename and instance deletion remove managed scopes, associations, mappings, and group grants")


if __name__ == "__main__":
    main()
