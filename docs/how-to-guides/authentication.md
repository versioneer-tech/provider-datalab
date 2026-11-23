# Authentication

Each Datalab has one confidential Keycloak client with the same name. For
example, the Datalab `s-joe` has a client named `s-joe` and its own service account.
Use that client for browser login, CLI device login, machine access, and
restricted user-token exchange. The same client credentials and Secret
references serve these flows.

The operator must configure the
[identity prerequisites](https://github.com/versioneer-tech/provider-datalab/blob/main/SECURITY.md#identity-prerequisites).

## Groups and roles

Users in `spec.users` must exist in the configured realm. The first user and
users with `userOverrides.<user>.role: admin` belong to the administrator group.
All listed users belong to the Datalab users group.

| Managed group or account | Assigned Datalab client roles |
| --- | --- |
| `<datalab>` | `ws_access`, `ws_api`, all explicitly configured additional vcluster profiles |
| `<datalab>-admin` | `ws_admin`, `ws_api`, all additional profiles, each instance's built-in cluster-admin role |
| Datalab service account | `ws_api` only |

Administrators also inherit the users group's grants. The provider replaces
managed group grants on each reconciliation. Profile removal or rename removes
its grants. Direct user assignments are unchanged.

Only `spec.vclusters.<instance>.groups` defines selectable exchange profiles.
The reserved `cluster-admin` entry never adds an exchange scope, even when
explicitly declared. Empty groups give regular members no vcluster roles;
administrators retain each declared instance's built-in admin role and profile.
Role names remain `vcluster_<instance>_<group>`.

## OAuth scopes and direct login

Tokens contain `ws_api` when the subject holds that role. Optional scopes
select additional roles from the subject's grants. The provider writes the
selected roles under `resource_access.<datalab>.roles`. Default identity
scopes are `basic`, `profile`, and `email`; see the
[identity requirements](https://github.com/versioneer-tech/provider-datalab/blob/main/SECURITY.md#identity-prerequisites).
For the mapper design and an example, see
[Token exchange for downscoping](../architecture/0003-token-exchange-for-downscoping.md).

| Optional OAuth scope | Permitted roles |
| --- | --- |
| `<datalab>:vclusters_<instance>_<group>` | Exactly `vcluster_<instance>_<group>` for an additional configured profile |
| `<datalab>:interactive` | `ws_access`, `ws_admin`, and each instance's built-in cluster-admin role |

Scopes permit only roles that the subject holds. They are never realm-default
scopes. Scope names differ from role names: bare `ws_admin` or
`vcluster_vc0_namespace-demo` are not generated OAuth scopes.

A direct authorization-code request to `s-joe` can use these parameters:

```text
client_id=s-joe
response_type=code
redirect_uri=http://localhost:8080/callback
scope=openid profile email s-joe:interactive s-joe:vclusters_vc0_namespace-demo
```

Add `http://localhost:8080/callback` to `EnvironmentConfig.data.iam.redirectURIs`
for this example. Set `iam.webOrigins` only for additional browser origins.
The Data callback is included by default.

For a namespace-only direct login, omit `s-joe:interactive`. Follow the
[login client requirements](https://github.com/versioneer-tech/provider-datalab/blob/main/SECURITY.md#login-clients)
when implementing the flow.

You can also use a separate login client in the same realm. Its scope mappings
control the roles in its tokens. Before exchanging one of those tokens through
the Datalab client, check that it contains the Datalab audience and the
requested roles. Configure those claims on the separate login client.

### CLI device login

The provider enables Device Authorization Grant on the existing confidential
client. The built-in `cluster-admin` kubeconfig helper uses this flow with
`openid offline_access <datalab>:interactive`. No localhost callback is needed.

The resulting access token represents the user who signs in. Only that user's
assigned roles can appear. Possession of the client secret does not grant
cluster-admin. The service account remains assigned only `ws_api`; the helper
does not use `grant_type=client_credentials`.

See [human access](vcluster.md#human-access) for login commands, credential
files, and token cache behavior. Additional profiles use a caller-supplied
access token and do not start login.

### Login lifetime

Keycloak sets these lifetimes; the helper uses the issued expiry values.

| Lifetime | Setting |
| --- | --- |
| Time to approve a device code | Realm `oauth2DeviceCodeLifespan` |
| Access token validity | Inherited realm Access Token Lifespan |
| CLI offline session validity | Offline Session Idle/Max and Client Offline Session Idle/Max |

The device helper can refresh tokens for up to 30 days, subject to realm
limits. See [human login lifetime](vcluster.md#human-login-lifetime) for cache
and revocation details. Exchanged tokens have no refresh token; longer
delegated access is discussed in
[ADR-004](../architecture/0004-token-lifetime-for-delegated-access.md).

## User-token exchange

Each Datalab client enables exchange automatically after its scopes, mappers,
and policy are ready. No extra setting is required.

Token exchange uses the Datalab client credentials and the caller's access
token. The result is limited by the caller's roles. Exchange rejects the
`<datalab>:interactive` scope, including requests that combine it with profile
scopes. Direct login can still use it.

Post this form to the configured realm's token endpoint and authenticate as
the confidential `s-joe` client:

```text
grant_type=urn:ietf:params:oauth:grant-type:token-exchange
subject_token=<caller access token>
subject_token_type=urn:ietf:params:oauth:token-type:access_token
requested_token_type=urn:ietf:params:oauth:token-type:access_token
scope=s-joe:vclusters_vc0_namespace-demo
audience=s-joe
```

The caller token must contain `s-joe` in `aud`, unless it was issued to
`s-joe` itself. Keycloak uses this check to confirm that the token was intended
for the Datalab client. The Datalab audience is always available in tokens
issued by that client. The `audience` parameter filters available audiences;
it does not add missing mappings.

For an eligible caller, the required authorization claims are:

```yaml
iss: https://identity.acme.com/realms/acme
sub: <same user subject as the caller token>
aud: [s-joe]
resource_access:
  s-joe:
    roles: [ws_api, vcluster_vc0_namespace-demo]
```

This applies to both members and administrators selecting the profile. The
result must omit `ws_access`, `ws_admin`, built-in cluster-admin, unrequested
profiles, and roles for other Datalabs. Identity claims can remain.

To use tokens issued by the Datalab client with another service, add its client ID to
`EnvironmentConfig.data.iam.extraAudiences`. For example, for
[EOEPCA Workspace API](https://github.com/EOEPCA/rm-workspace-api/):

```yaml
iam:
  extraAudiences:
  - workspace-api
```

An exchange request can then include both `audience=s-joe` and
`audience=workspace-api` to retain those two recipients. Removing the setting
removes its managed audience mapper. For tokens issued by a separate login
client, configure the Datalab audience on that client.

Keycloak checks the user's role grants before applying an optional profile
scope. A user without the role can receive a successful response with that
scope and role omitted. Consumers must reject a result missing a requested
role. See
[Keycloak scope permissions](https://www.keycloak.org/docs/latest/server_admin/index.html#_client_scopes_permissions).

Reconciliation removes a deleted or renamed profile's optional association,
role scope mapping, Client Scope, and managed group grants. Instance deletion
removes its profiles too. Already-issued JWTs can retain their claims until
expiry. Downloading a kubeconfig profile neither grants permissions nor
reduces a supplied token's permissions. For delegated access, exchange the
token first, then give the recipient the profile and returned access token.
The additional profile helper reads that token from a file and needs no client
secret. The virtual API still checks the realm issuer, Datalab audience,
signature, validity, and configured Datalab roles.
Its username is `sub`; groups are `datalab:<datalab>:<role>`. Virtual
RoleBinding and ClusterRoleBinding rules apply.

## Credential Secrets and machine access

Workload clients use the [virtual API and Kubernetes RBAC](vcluster.md#api-access).
They do not need the runtime OAuth Secret below. See
[Workload access](https://github.com/versioneer-tech/provider-datalab/blob/main/SECURITY.md#workload-access) for the network boundary.

| Secret | Namespace | Use |
| --- | --- | --- |
| `<datalab>-oauth-client` | Claim namespace | Source credentials for the existing Datalab client |
| `<datalab>-oauth2-client` | Runtime namespace | Created only for public Data/S3 OAuth2 proxies; contains `client_id`, `client_secret`, and `cookie_secret` |

The runtime copy is needed only when Data is enabled and exposed through an
Ingress or HTTPRoute. It uses the Datalab service namespace and is removed
when that proxy is disabled. Token exchange and virtual-cluster access do not
need this copy. Storage and database Secrets do not contain OAuth credentials.

Anyone with the client secret can request a service-account token. Grant read
access only to authorized callers. With `grant_type=client_credentials` and no
optional scopes, the Datalab service account receives only
`ws_api`.

Virtual API profile Secrets contain public settings and no credentials. See
[virtual API access](vcluster.md#api-access) for credential files. Permission to
download a profile is separate from permission to read service credentials.

Before integrating exchange into a service, apply the
[caller checks](https://github.com/versioneer-tech/provider-datalab/blob/main/SECURITY.md#token-exchange-callers).

## OAuth2 discovery

The provider publishes the existing client in `status.oauth2`, separately from
service connections:

```yaml
status:
  oauth2:
  - name: s-joe
    type: client
    issuerUrl: https://identity.acme.com/realms/acme
    secretRef:
      name: s-joe-oauth-client
      namespace: workspace
    ready: true
```

`name` is the actual OAuth2 client ID, not Keycloak's internal UUID. Names are
unique and `type` is always `client`. Entries contain only metadata and Secret
references; credentials stay in the referenced Secret.

Readiness requires the observed client and credential Secret to be ready, with
matching client credentials. Removed sources clear stale entries. Discovery
does not grant permission to read a Secret or authorize a service request.
