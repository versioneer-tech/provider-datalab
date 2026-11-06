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
    assert client["oauth2DeviceAuthorizationGrantEnabled"] and not client["standardTokenExchangeEnabled"]
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
    usages = [body["spec"] for body in initial.values() if body.get("kind") == "Usage"]
    assert {item["of"]["kind"] for item in usages} == {"ClientScope", "ClientPolicyProfile"}
    assert all(item["replayDeletion"] and item["by"]["kind"] == "ClientPolicyProfilePolicy"
               and item["by"]["resourceRef"]["name"] == policy["name"] for item in usages)
    mappers = params(initial, "ProtocolMapper")
    assert {item["config"]["included.client.audience"] for item in mappers
            if item["protocolMapper"] == "oidc-audience-mapper"} == {"s-joe"}
    role_mapper, = [item for item in mappers if item["protocolMapper"] == "oidc-usermodel-realm-role-mapper"]
    assert role_mapper["config"]["claim.name"] == "resource_access.s-joe.roles"
    collector, = [body for body in initial.values() if body.get("kind") == "ProtocolMapper"
                  and body["spec"]["forProvider"]["protocolMapper"] == "oidc-usermodel-realm-role-mapper"]
    assert collector["metadata"]["name"] != "s-joe"
    assert not any(item["protocolMapper"] in {"oidc-usermodel-client-role-mapper", "oidc-hardcoded-role-mapper", "oidc-hardcoded-claim-mapper"}
                   for item in mappers)
    selected = [item for item in mappers if item["protocolMapper"] == "oidc-role-name-mapper"]
    baseline, = [item for item in selected if "clientIdRef" in item]
    assert baseline["config"] == {"role": "s-joe.ws_api", "new.role.name": "ws_api"}
    selected_scopes = {}
    for item in selected:
        role = item["config"]["new.role.name"]
        assert item["config"]["role"] == "s-joe." + role
        if "clientScopeIdRef" in item:
            selected_scopes.setdefault(scopes[item["clientScopeIdRef"]["name"]], set()).add(role)
    assert selected_scopes == optional
    assert not any(item.get("kind") in {"Realm", "DefaultClientScopes", "OptionalClientScopes"} for item in initial.values())
    assert all(item["clientIdRef"]["name"] == "s-joe" for item in mappers if "clientIdRef" in item)
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
    other_usage = deepcopy(next(body for body in observed if body["kind"] == "Usage"))
    other_usage["metadata"]["name"] = "s-joe-vcluster-control-plane-usage"
    other_usage["metadata"]["annotations"]["crossplane.io/composition-resource-name"] = "vcluster-usage-vc0-control-plane"
    assert params(render(args, env, source, [*observed, other_usage]), "Client")[0]["standardTokenExchangeEnabled"]
    native_usage = deepcopy(observed)
    for body in native_usage:
        if body.get("kind") == "Usage":
            body["status"]["conditions"] = [{"type": "Ready", "status": "True"}]
    assert params(render(args, env, source, native_usage), "Client")[0]["standardTokenExchangeEnabled"]
    stale = deepcopy(next(body for body in observed if body["kind"] == "RoleMapper" and "clientIdRef" in body["spec"]["forProvider"]))
    stale["metadata"]["annotations"]["crossplane.io/composition-resource-name"] = "keycloak-role-mapper-user-s-joe-ws-access"
    assert not params(render(args, env, source, [*observed, stale]), "Client")[0]["standardTokenExchangeEnabled"]
    old_mapper = deepcopy(next(body for body in observed if body.get("kind") == "ProtocolMapper"))
    old_mapper["metadata"]["annotations"]["crossplane.io/composition-resource-name"] = "keycloak-client-roles-s-joe"
    old_mapper["spec"]["forProvider"]["protocolMapper"] = "oidc-usermodel-client-role-mapper"
    assert not params(render(args, env, source, [*observed, old_mapper]), "Client")[0]["standardTokenExchangeEnabled"]
    pending = deepcopy(observed)
    next(body for body in pending if body["kind"] == "ClientPolicyProfilePolicy")["status"]["conditions"][0]["status"] = "False"
    assert not params(render(args, env, source, pending), "Client")[0]["standardTokenExchangeEnabled"]
    pending_usage = deepcopy(observed)
    next(body for body in pending_usage if body["kind"] == "Usage")["status"]["conditions"][0]["status"] = "False"
    assert not params(render(args, env, source, pending_usage), "Client")[0]["standardTokenExchangeEnabled"]
    print("PASS exchange waits for reconciled restrictions and removal of old broad mappings")

    renamed = deepcopy(source)
    renamed["spec"]["vclusters"]["vc0"]["groups"][0]["name"] = "renamed"
    changed = render(args, env, renamed, observed)
    old_keys = {key for key, body in initial.items() if body["kind"] in {"ClientScope", "RoleMapper", "ProtocolMapper"}
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
