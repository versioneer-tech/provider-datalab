# Authentication

Each Datalab has one confidential Keycloak client with the same name. For
example, the Datalab `s-joe` has a client named `s-joe` and its own service account.
Use that client for browser login, machine access, and restricted user-token
exchange. The same client credentials and Secret references serve these flows.

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

The Datalab client's dedicated role mapping permits only `ws_api`. It
appears in a token only if its subject holds that role. Default scopes are
`basic`, `profile`, and `email`; keep these scopes free of role grants and role
mappers. Keycloak includes a client's own roles even with Full Scope Allowed
off. The provider therefore uses Role Name mappers to select held roles for
each request, then a Realm Roles mapper to write that temporary role set under
`resource_access.<datalab>.roles`. This creates no realm roles or user grants.
For the reason and a worked example, see
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

Use the normal state and PKCE checks, then authenticate the confidential client
when redeeming the code. Request only the scopes needed by the application.
For a namespace-only direct login, omit `s-joe:interactive`.


You can also use a separate login client in the same realm. Its scope mappings
control the roles in its tokens. Before exchanging one of those tokens through
the Datalab client, check that it contains the Datalab audience and the
requested roles. Configure those claims on the separate login client.

## User-token exchange

Each Datalab client enables exchange automatically after its scopes, mappers,
and policy are ready. No extra setting is required.

Standard Token Exchange V2 uses the existing Datalab client credentials. The caller's
access token remains the subject; exchange does not use the service account's
permissions. A managed client policy combines the `grant-type` and
`client-scopes` conditions with `reject-request`. It rejects
`<datalab>:interactive` during token exchange, including requests that combine
it with allowed profile scopes. Direct interactive login can still use it.

Send this form to the configured realm's token endpoint. Authenticate with the
existing confidential `s-joe` client through the approved credential path.
The placeholder below represents the original caller access token.

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
role. This is the documented server behavior; actual issuance must be checked
against the deployed server. Render checks do not prove token contents. See
[Keycloak scope permissions](https://www.keycloak.org/docs/latest/server_admin/index.html#_client_scopes_permissions).

Reconciliation removes a deleted or renamed profile's optional association,
role scope mapping, Client Scope, and managed group grants. Instance deletion
removes its profiles too. Already-issued JWTs can retain their claims until
expiry. Downloading a kubeconfig profile neither grants permissions nor
reduces a supplied token's permissions. The virtual API still checks the realm
issuer, Datalab audience, signature, validity, and configured Datalab roles.
Its username is `sub`; groups are `datalab:<datalab>:<role>`. Existing virtual
RoleBinding and ClusterRoleBinding rules apply without an authentication change.

## Credential Secrets and machine access

| Secret | Namespace | Use |
| --- | --- | --- |
| `<datalab>-oauth-client` | Claim namespace | Source credentials for the existing Datalab client |
| `<datalab>-oauth2-client` | Runtime namespace | Created only for public Data/S3 OAuth2 proxies; contains `client_id`, `client_secret`, and `cookie_secret` |

The runtime copy is needed only when Data is enabled and exposed through an
Ingress or HTTPRoute. It is created after the runtime namespace is known and
removed when that proxy is disabled. Token exchange and virtual-cluster access
do not need this copy. The legacy aggregate Secret still includes OAuth fields
delivered to sessions.

Anyone with the client secret can request a service-account token. Grant read
access only to authorized callers. With `grant_type=client_credentials` and no
optional scopes, the Datalab service account receives only
`ws_api`.

Virtual API profile Secrets contain public settings and no credentials. See
[virtual API access](vcluster.md#api-access) for credential files. Permission to
download a profile is separate from permission to read service credentials.

## Exchange caller checks

A service that exchanges tokens for users must:

- Accept full profile scope names, or translate short names with the Datalab name.
- Allow only currently configured additional profiles and check each requested
  role against the caller's validated token.
- Retain the original caller access token for `subject_token` and authenticate
  exchange with the existing Datalab client credentials.
- Validate the returned signature, validity, issuer, exact audiences, user
  subject, requested roles, and absence of unexpected authorization permissions.
- Reject missing requested roles even when the token endpoint returns success.
- Check that the caller is allowed to request token issuance through that
  service, in addition to the token and role checks above.

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

## Session ingress

Configure sign-in before users start a session. The examples use Kyverno to
configure NGINX or APISIX session Ingress objects.

### Set the shared ingress settings

Set the ingress class, domain, and TLS Secret in the
[EnvironmentConfig](installation.md#identity-and-endpoints). Use the same
values in the session runtime installation, for example:

```yaml
clusterIngressDomain: lab.acme.com
clusterIngressClass: apisix
tlsCertificateRef:
  name: wildcard-tls
  namespace: workspace
```

Use a wildcard certificate for `*.lab.acme.com`.

### Generated session resources

For a Datalab named `s-jane` with a `default` session, set `ingress.domain` to
`lab.acme.com`. The session ingress hosts include:

```text
s-jane-default.lab.acme.com
editor-s-jane-default.lab.acme.com
s-jane-default-editor.lab.acme.com
data-s-jane-default.lab.acme.com
s-jane-default-data.lab.acme.com
```

The generated ingresses carry labels that are suitable for platform policy:

```yaml
training.educates.dev/application: workshop
training.educates.dev/component: session
training.educates.dev/environment.name: s-jane
```

For `s-jane`, the generated client includes redirect and web-origin entries
for the Datalab root and each declared session host:

```text
https://s-jane.lab.acme.com/*
https://s-jane-default.lab.acme.com/*
https://editor-s-jane-default.lab.acme.com/*
https://s-jane-default-editor.lab.acme.com/*
https://data-s-jane-default.lab.acme.com/*
https://s-jane-default-data.lab.acme.com/*
http://localhost:*
```

A service that belongs to `s-jane` can use this client. Shared browser ingress
can use a central platform client and check the generated Datalab roles.

### Apply ingress policy

Apply controller settings through platform policy so they cover every session
Ingress. The examples use Kyverno CEL policies. They need CRDs that serve
`MutatingPolicy` and `GeneratingPolicy` in `policies.kyverno.io/v1`.
Kyverno is required for these policies, not for Provider Datalab itself.
Adapt the domains, issuer, and controller settings in the linked manifests.

#### NGINX Ingress with OAuth2 Proxy

Run OAuth2 Proxy as a shared service with its own OAuth client. Use a redirect
URI such as `https://auth.lab.acme.com/oauth2/callback`. Its authorization
policy must check access to the Datalab named in the requested host.

Apply the [NGINX policy](https://github.com/versioneer-tech/provider-datalab/blob/main/examples/ingress-protection/nginx-oauth2-proxy-workshop-session-protection.yaml)
to add external-auth annotations to matching session Ingress objects.
Set the proxy cookie domain to cover the session hosts, for example
`.lab.acme.com`, and allow redirects only to that domain.

#### APISIX Ingress configured by Kyverno

The [APISIX manifest](https://github.com/versioneer-tech/provider-datalab/blob/main/examples/ingress-protection/apisix-workshop-session-protection.yaml)
gives Kyverno permission to create `ApisixPluginConfig` resources, generates
one in each session namespace, and attaches it to matching Ingress objects.
APISIX checks incoming requests; Kyverno configures the resources.

The example uses `openid-connect` with a central public client named
`datalab-sessions`. Its `opa` entry points to an external OPA service.
The manifest does not deploy that service or supply its policy. Configure
both for your platform so that the authorizer checks access to the requested
Datalab. OPA is needed only for this example.

The policies do not read Secrets. For a confidential central client, use the
ingress controller's supported Secret mechanism to supply its credential.

The plugin forwards the access token in `Authorization` and disables ID token,
userinfo, and refresh token forwarding. Check that your authorizer and
upstream service accept these settings.

Kyverno generates the plugin's session secret once. Synchronization is disabled
to keep it stable. After changing the template, recreate an existing generated
plugin config or restart its session to apply the change.

For another ingress controller, match session Ingress objects by label and
domain, then attach its authentication and authorization settings.
