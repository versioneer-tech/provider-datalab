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

## Apply ingress policy

Apply controller settings through platform policy so they cover every session
Ingress. These examples use Kyverno CEL policies. Kyverno is needed only for
these examples, not by Provider Datalab itself. Check that the installed Kyverno
CRDs serve `MutatingPolicy` and `GeneratingPolicy` in `policies.kyverno.io/v1`.

For the other access controls, see [Security](../security/index.md).

## Generated session resources

For a Datalab named `s-jane` with a `default` session, set `ingress.domain` to
`lab.acme.org`. Educates then creates session ingress hosts such as:

```text
s-jane-default.lab.acme.org
editor-s-jane-default.lab.acme.org
s-jane-default-editor.lab.acme.org
data-s-jane-default.lab.acme.org
s-jane-default-data.lab.acme.org
```

The generated ingresses carry labels that are suitable for platform policy:

```yaml
training.educates.dev/application: workshop
training.educates.dev/component: session
training.educates.dev/environment.name: s-jane
```

Provider Datalab also creates a confidential Keycloak client named after the
Datalab. For `s-jane`, the generated client includes redirect and web-origin
entries for the Datalab root and each declared session host:

```text
https://s-jane.lab.acme.org/*
https://s-jane-default.lab.acme.org/*
https://editor-s-jane-default.lab.acme.org/*
https://s-jane-default-editor.lab.acme.org/*
https://data-s-jane-default.lab.acme.org/*
https://s-jane-default-data.lab.acme.org/*
http://localhost:*
```

A service that belongs to `s-jane` can use this client. Shared browser ingress
can use a central platform client and check the generated Datalab roles.

To call a Datalab-owned service with a machine token, read `client_id` and
`client_secret` from `<datalab>-oauth2-client`, request a token with
`grant_type=client_credentials`, then send that access token to the service. Its
policy should require `ws_api` and any configured audience.

## Set the shared ingress settings

Change `ingress.class` to match the ingress controller you operate.

```yaml
apiVersion: apiextensions.crossplane.io/v1beta1
kind: EnvironmentConfig
metadata:
  name: datalab
data:
  iam:
    realm: acme
  ingress:
    class: apisix # use "nginx" for the nginx example
    domain: lab.acme.org
    secret: workspace-tls
  storage:
    endpoint: https://s3.acme.org
    provider: Other
    region: acme
    forcePathStyle: "true"
    secretNamespace: workspace
    type: s3
```

The Educates installation must use the same ingress class, domain, and TLS
secret. For example, an APISIX-based deployment would set:

```yaml
clusterIngressDomain: lab.acme.org
clusterIngressClass: apisix
tlsCertificateRef:
  name: workspace-tls
  namespace: workspace
```

For TLS, use a wildcard certificate for the session domain:

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: workspace-cert
  namespace: workspace
spec:
  dnsNames:
  - "*.lab.acme.org"
  issuerRef:
    kind: ClusterIssuer
    name: letsencrypt-dns-prod
  secretName: workspace-tls
```

## NGINX Ingress with OAuth2 Proxy

Run OAuth2 Proxy as a shared service and add external-auth annotations to the
session Ingress objects.

Give that proxy its own OAuth client with a redirect URI such as:

```text
https://auth.lab.acme.org/oauth2/callback
```

The shared proxy can use one client for all Datalabs. Its authorization policy
must still check access to the Datalab named in the requested host.

```yaml
apiVersion: policies.kyverno.io/v1
kind: MutatingPolicy
metadata:
  name: protect-workshop-sessions-nginx
spec:
  failurePolicy: Fail
  evaluation:
    admission:
      enabled: true
    background:
      enabled: false
  matchConstraints:
    resourceRules:
      - apiGroups: [networking.k8s.io]
        apiVersions: [v1]
        operations: [CREATE, UPDATE]
        resources: [ingresses]
  matchConditions:
    - name: is-workshop-session
      expression: >-
        has(object.metadata.labels) &&
        'training.educates.dev/application' in object.metadata.labels &&
        object.metadata.labels['training.educates.dev/application'] == 'workshop' &&
        'training.educates.dev/component' in object.metadata.labels &&
        object.metadata.labels['training.educates.dev/component'] == 'session'
    - name: uses-nginx
      expression: >-
        has(object.spec.ingressClassName) &&
        object.spec.ingressClassName == 'nginx'
    - name: uses-datalab-domain
      expression: >-
        has(object.spec.rules) && object.spec.rules.exists(rule,
          has(rule.host) && rule.host.endsWith('.lab.acme.org'))
  mutations:
    - patchType: ApplyConfiguration
      applyConfiguration:
        expression: |
          Object{
            metadata: Object.metadata{
              annotations: {
                "nginx.ingress.kubernetes.io/auth-url": "https://auth.lab.acme.org/oauth2/auth",
                "nginx.ingress.kubernetes.io/auth-signin": "https://auth.lab.acme.org/oauth2/start?rd=https://$host$escaped_request_uri",
                "nginx.ingress.kubernetes.io/auth-response-headers": "Authorization,X-Auth-Request-User,X-Auth-Request-Email,X-Auth-Request-Preferred-Username"
              }
            }
          }
```

Set the proxy cookie domain to cover the session hosts, for example
`.lab.acme.org`, and allow redirects only to that domain.

## APISIX Ingress configured by Kyverno

The Kyverno generating policy creates an `ApisixPluginConfig` in the session
namespace. The mutating policy adds its name to the Ingress annotation.
APISIX then uses that configuration for incoming requests. Kyverno configures
the Ingress; it does not check browser tokens on each request.

The existing repository example uses `openid-connect` with a central client
named `datalab-sessions`. It also contains an `opa` plugin entry that points
to an external OPA service. The example does not deploy that service or supply
its policy. Use that entry only with an OPA service configured by your
platform. Provider Datalab itself does not require OPA.

Kyverno needs permission to create `ApisixPluginConfig` resources in the
generated session namespaces:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: kyverno:datalab-session-apisix-pluginconfigs
  labels:
    rbac.kyverno.io/aggregate-to-admission-controller: "true"
    rbac.kyverno.io/aggregate-to-background-controller: "true"
rules:
- apiGroups:
  - apisix.apache.org
  resources:
  - apisixpluginconfigs
  verbs:
  - get
  - list
  - watch
  - create
  - update
  - patch
  - delete
```

The Kyverno policies below do not need Secret read access because they use a
central public OAuth client. If your platform uses a confidential central
client, inject that platform-managed credential with the ingress controller's
supported Secret mechanism instead of the generated per-Datalab runtime Secret.

The CEL policies generate one APISIX plugin config per session namespace and
annotate the matching workshop ingress to use it:

```yaml
apiVersion: policies.kyverno.io/v1
kind: GeneratingPolicy
metadata:
  name: generate-workshop-session-apisix-pluginconfigs
spec:
  evaluation:
    synchronize:
      enabled: false
  matchConstraints:
    resourceRules:
      - apiGroups: [networking.k8s.io]
        apiVersions: [v1]
        operations: [CREATE, UPDATE]
        resources: [ingresses]
  matchConditions:
    - name: is-workshop-session
      expression: >-
        has(object.metadata.labels) &&
        'training.educates.dev/application' in object.metadata.labels &&
        object.metadata.labels['training.educates.dev/application'] == 'workshop' &&
        'training.educates.dev/component' in object.metadata.labels &&
        object.metadata.labels['training.educates.dev/component'] == 'session'
    - name: uses-apisix
      expression: >-
        has(object.spec.ingressClassName) &&
        object.spec.ingressClassName == 'apisix'
    - name: uses-datalab-domain
      expression: >-
        has(object.spec.rules) && object.spec.rules.exists(rule,
          has(rule.host) && rule.host.endsWith('.lab.acme.org'))
    - name: has-datalab-name
      expression: >-
        'training.educates.dev/environment.name' in object.metadata.labels &&
        object.metadata.labels['training.educates.dev/environment.name'] != ''
  variables:
    - name: environmentName
      expression: object.metadata.labels['training.educates.dev/environment.name']
    - name: targetNamespace
      expression: object.metadata.namespace
  generate:
    - template:
        interpolate: cel
        value: |
          apiVersion: apisix.apache.org/v2
          kind: ApisixPluginConfig
          metadata:
            name: datalab-session-oidc-(( variables.environmentName ))
            namespace: (( variables.targetNamespace ))
            labels:
              training.educates.dev/application: workshop
              training.educates.dev/component: session
              training.educates.dev/environment.name: (( variables.environmentName ))
          spec:
            plugins:
              - name: openid-connect
                enable: true
                config:
                  discovery: "https://iam-auth.acme.org/realms/acme/.well-known/openid-configuration"
                  use_jwks: true
                  bearer_only: false
                  scope: openid profile email roles
                  client_id: datalab-sessions
                  client_secret: ""
                  session:
                    secret: (( random.random('[A-Za-z0-9]{32}') ))
                  access_token_in_authorization_header: true
                  set_access_token_header: true
                  set_id_token_header: false
                  set_userinfo_header: false
                  set_refresh_token_header: false
              - name: opa
                enable: true
                config:
                  host: http://opa.iam:8181
                  policy: example/datalab/session
---
apiVersion: policies.kyverno.io/v1
kind: MutatingPolicy
metadata:
  name: annotate-workshop-sessions-for-apisix
spec:
  failurePolicy: Fail
  evaluation:
    admission:
      enabled: true
    background:
      enabled: false
  matchConstraints:
    resourceRules:
      - apiGroups: [networking.k8s.io]
        apiVersions: [v1]
        operations: [CREATE, UPDATE]
        resources: [ingresses]
  matchConditions:
    - name: is-workshop-session
      expression: >-
        has(object.metadata.labels) &&
        'training.educates.dev/application' in object.metadata.labels &&
        object.metadata.labels['training.educates.dev/application'] == 'workshop' &&
        'training.educates.dev/component' in object.metadata.labels &&
        object.metadata.labels['training.educates.dev/component'] == 'session'
    - name: uses-apisix
      expression: >-
        has(object.spec.ingressClassName) &&
        object.spec.ingressClassName == 'apisix'
    - name: uses-datalab-domain
      expression: >-
        has(object.spec.rules) && object.spec.rules.exists(rule,
          has(rule.host) && rule.host.endsWith('.lab.acme.org'))
    - name: has-datalab-name
      expression: >-
        'training.educates.dev/environment.name' in object.metadata.labels &&
        object.metadata.labels['training.educates.dev/environment.name'] != ''
  variables:
    - name: environmentName
      expression: object.metadata.labels['training.educates.dev/environment.name']
  mutations:
    - patchType: ApplyConfiguration
      applyConfiguration:
        expression: |
          Object{
            metadata: Object.metadata{
              annotations: {
                "k8s.apisix.apache.org/plugin-config-name":
                  "datalab-session-oidc-" + variables.environmentName
              }
            }
          }
```

The external authorizer in this example must check access to the requested
Datalab. Its endpoint and policy path are placeholders for the platform's
settings.

The session secret is generated when Kyverno creates the `ApisixPluginConfig`.
Disabled synchronization keeps the generated object stable. If you change the
plugin template for an existing session, recreate the generated plugin config or
restart the session so Kyverno can generate a new one.

This example forwards the access token in the `Authorization` header and
disables ID token, userinfo, and refresh token forwarding. Check that those
settings match the authorization plugins and upstream service you use.

For another ingress controller, match the session Ingress objects by label and
domain, then attach its authentication and authorization settings.

The complete manifests are in the repository:

- [NGINX and OAuth2 Proxy](https://github.com/versioneer-tech/provider-datalab/blob/main/examples/ingress-protection/nginx-oauth2-proxy-workshop-session-protection.yaml)
- [APISIX Kyverno policies](https://github.com/versioneer-tech/provider-datalab/blob/main/examples/ingress-protection/apisix-workshop-session-protection.yaml)
