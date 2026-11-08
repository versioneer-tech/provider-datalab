# ADR-003: Token Exchange for Downscoping

> Written: 04.11.2026.

## Status

Accepted

## Context

The simple pattern is to use a service account with `ws_api`. Each Datalab has
a Keycloak client with the same name and its own service account. This is enough
for services that accept `ws_api`. That role does not give access to a virtual
cluster. Some tasks need more permissions, such as writing data in one virtual
namespace. For those tasks, we let a user
delegate part of their access through token exchange. The request selects an
OAuth scope, and the new token keeps the user's identity with fewer roles.

Device and standard flows inherit the realm's access-token lifespan. Device
login requests offline access, so the helper can refresh these short-lived
tokens for up to 30 days, subject to the realm's offline-session limits.
Exchanged access tokens inherit the same realm lifespan and have no refresh
token in the current setup. Options for longer delegated access are discussed
in [ADR-004](0004-token-lifetime-for-delegated-access.md).

Selecting one scope does not always exclude the user's other roles. Keycloak
includes user-held roles owned by the requesting client, even with Full Scope
Allowed off.

### Separate role definitions from role assignments

Consider a Datalab named `s-joe`, with two virtual clusters and these roles defined
under its Keycloak client:

```text
s-joe
  ws_api
  ws_access
  ws_admin
  vcluster_vc0_cluster-admin
  vcluster_vc0_namespace-demo
  vcluster_vc1_cluster-admin
  vcluster_vc1_namespace-other
```

This list defines the roles that belong to the client. Role assignments say
who holds them. The service account holds only `ws_api`. Joe, a Datalab
administrator, holds all seven through the Datalab users and administrator
groups. A regular member holds `ws_access`, `ws_api`, and the two additional
namespace roles, without the built-in administrator roles.

In a client-credentials request, the service account is the token's subject.
In a user-token exchange, Joe is the subject. The Datalab client authenticates
the exchange request, but its service account's role list does not limit Joe's
roles.

### The broad role mapper breaks downscoping

Suppose Joe asks a service to write data in namespace `demo` of `vc0`. The
service exchanges his access token with these parameters and the existing
Datalab client credentials:

```text
grant_type=urn:ietf:params:oauth:grant-type:token-exchange
subject_token=<Joe's access token>
scope=s-joe:vclusters_vc0_namespace-demo
audience=s-joe
```

The intended result contains `ws_api` and `vcluster_vc0_namespace-demo`.

Keycloak includes roles that the subject holds under the requesting client,
even when Full Scope Allowed is off. A broad Client Roles mapper then writes
all of those roles into `resource_access.s-joe.roles`. In this example, that
means all seven roles above, including administration of both virtual clusters.
The optional namespace scope does not filter them out.

Joe has not gained a new permission. The service that receives his exchanged
token has received more access than this task needs. It can use his virtual
cluster administrator roles even though the request selected one namespace.
Keeping `ws_api` is expected; keeping those unrequested roles defeats the
purpose of the exchange.

This behavior comes from Keycloak's
[role selection](https://github.com/keycloak/keycloak/blob/26.8.1/services/src/main/java/org/keycloak/protocol/oidc/TokenManager.java#L572-L604).
It is not an extra grant made by the test or the Datalab service account.

## Decision

### Select the emitted roles explicitly

The Datalab client uses `basic`, `profile`, and `email` as identity-only
default scopes. Each additional vcluster profile has an optional scope, so the
caller must request it explicitly.

Each profile scope uses Keycloak's built-in Role Name mapper to select its one
role, but only when the user holds that role. A dedicated mapper selects
`ws_api` under the same rule. These mappers put the selected roles into a
temporary role set for the current request. A built-in Realm Roles mapper writes
that set into `resource_access.<datalab>.roles`. This creates no stored realm
roles or new user assignments. It needs no script or custom Keycloak plugin.

Joe's namespace request then produces:

```yaml
sub: <Joe's user ID>
aud: [s-joe]
resource_access:
  s-joe:
    roles:
    - ws_api
    - vcluster_vc0_namespace-demo
```

The token cannot carry Joe's administrator roles or the other namespace profile
unless the selected scopes permit them. A user without the requested profile
role receives no such role; the service must check the result before using it.
A hardcoded claim would not make that check against the user's assignments.

### Keep interactive roles out of exchanged tokens

The separate optional `s-joe:interactive` scope supplies Datalab and built-in
administrator roles for direct browser login. A client policy rejects this
scope during token exchange, including requests that mix it with a namespace
scope. Otherwise, a caller could request it and defeat the restriction.

### Enable exchange only after its controls are ready

Each Datalab client enables exchange automatically after its scopes, mappers,
and policy are ready. There is no platform opt-in setting. Crossplane Usage
resources keep a policy's scope and profile until the policy has been deleted.

Keycloak 26.2 or later is required. Default identity scopes must contain no
role grants or role mappers.

## Consequences

- A service can receive a token for one configured profile while the user keeps
  their wider Datalab permissions. The user's identity stays in the token.
- The platform must provide identity-only default scopes. A service account
  with `ws_api` alone cannot access a virtual cluster.
- Render tests check configuration. Live tests must inspect issued user tokens
  and use them against the virtual API. Namespace access must work, cluster
  access must fail, unassigned roles must stay absent, and exchange with the
  interactive scope must fail.
- Selecting a kubeconfig profile alone does not reduce a token's permissions.
