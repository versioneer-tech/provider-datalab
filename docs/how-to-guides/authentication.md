# Authentication

The platform ingress controller protects Datalab sessions. Configure sign-in
and authorization before users start a session. The examples below use Kyverno
policies to configure NGINX or APISIX session Ingress objects.

## Keycloak clients and roles

Users in `spec.users` must already exist in the realm selected by
`EnvironmentConfig.data.iam.realm`. Provider Datalab creates a confidential
client named after the Datalab, groups for its users and administrators, and
their memberships and role mappings. The client disables implicit, device,
and direct access grants. Role scope mappings limit the Datalab client roles
included in its tokens.

| Role | Assigned to | Used for |
| --- | --- | --- |
| `ws_access` | Datalab users | Browser access |
| `ws_admin` | Datalab administrators | Browser access with the admin role |
| `ws_api` | The client service account | Machine access through client credentials |

The runtime Secret `<datalab>-oauth2-client` contains `client_id` and
`client_secret`. Anyone who can read it can request a machine token for that
Datalab. Give access only to users and services that need it.

A service can require extra token audiences. List them in
`EnvironmentConfig.data.iam.extraAudiences` and use the same values in the
service's token checks. The S3 endpoint adds the Datalab client ID as an
audience when enabled. Other OAuth clients that call these services must emit
the required audience and roles too.

## Generated session resources

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

To call a Datalab-owned service with a machine token, read `client_id` and
`client_secret` from `<datalab>-oauth2-client`, request a token with
`grant_type=client_credentials`, then send that access token to the service. Its
policy should require `ws_api` and any configured audience.

## Set the shared ingress settings

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

## Apply ingress policy

Apply controller settings through platform policy so they cover every session
Ingress. The examples use Kyverno CEL policies. They need CRDs that serve
`MutatingPolicy` and `GeneratingPolicy` in `policies.kyverno.io/v1`.
Kyverno is required for these policies, not for Provider Datalab itself.
Adapt the domains, issuer, and controller settings in the linked manifests.

### NGINX Ingress with OAuth2 Proxy

Run OAuth2 Proxy as a shared service with its own OAuth client. Use a redirect
URI such as `https://auth.lab.acme.com/oauth2/callback`. Its authorization
policy must check access to the Datalab named in the requested host.

Apply the [NGINX policy](https://github.com/versioneer-tech/provider-datalab/blob/main/examples/ingress-protection/nginx-oauth2-proxy-workshop-session-protection.yaml)
to add external-auth annotations to matching session Ingress objects.
Set the proxy cookie domain to cover the session hosts, for example
`.lab.acme.com`, and allow redirects only to that domain.

### APISIX Ingress configured by Kyverno

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
