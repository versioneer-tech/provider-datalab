# Authentication

Each Datalab has one Keycloak client for browser and machine access. Virtual
APIs validate the caller's token. The platform ingress controller enforces
browser sign-in and authorization for sessions.

## Keycloak clients and roles

Users in `spec.users` must exist in the realm selected by
`EnvironmentConfig.data.iam.realm`. The provider creates a confidential client
named after the Datalab, user and administrator groups, and their memberships.
The client disables implicit, device, and direct access grants. Scope mappings
limit which assigned client roles can appear in tokens; they do not grant roles.

| Role | Assigned to | Used for |
| --- | --- | --- |
| `ws_access` | Datalab users | Browser access |
| `ws_admin` | Datalab administrators | Browser access with the admin role |
| `ws_api` | The client service account | Machine access through client credentials |

Virtual APIs require a configured vcluster role as well as the Datalab audience.
The workspace service account has only `ws_api` by default and cannot access
those APIs until an identity administrator explicitly assigns a vcluster role.
Datalab users receive each instance's built-in admin role through the users group.
See [virtual API access](vcluster.md#api-access) for role boundaries and caller
credential files.

## Credential Secrets

| Secret | Namespace | Use |
| --- | --- | --- |
| `<datalab>-oauth-client` | Claim namespace | Source credentials for the existing workspace client |
| `<datalab>-oauth2-client` | Runtime namespace | Credential copy used by Datalab services, with `client_id` and `client_secret` |

Anyone with the client secret can request a token as its service account.
Grant read access only to callers authorized to use that identity. Virtual API
profile Secrets contain public connection settings and no authentication
credentials. Permission to download a profile is separate from permission to
read OAuth2, database, registry, or other service credentials.

## Tokens and audiences

For machine access, exchange the workspace client ID and secret with
`grant_type=client_credentials`, then send the access token to the service.
Each service must check its required roles and audience. The virtual API
helper accepts the secret in a separate file; see [machine access](vcluster.md#machine-access).

List additional token audiences in `EnvironmentConfig.data.iam.extraAudiences`.
The provider adds the Datalab client ID as an audience when its S3 endpoint or
named virtual APIs are enabled. Other OAuth clients that call these services
must emit the required Datalab audience and roles too.

## OAuth2 discovery

The provider publishes the existing client in `status.oauth2`, separately from
service connections:

```yaml
status:
  oauth2:
  - name: ws-alice
    type: client
    issuerUrl: https://identity.example.org/realms/eoepca
    secretRef:
      name: ws-alice-oauth-client
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
