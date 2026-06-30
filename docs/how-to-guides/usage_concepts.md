# Provider Datalab – Usage & Concepts

This section explains how to use the `provider-datalab` configuration packages once they are installed. Read it as an operator-facing contract that software engineers and workspace users can also understand.

A `Datalab` gives users a smooth workspace, but durable state should stay visible to the platform team: object-storage credentials, persistent volumes, databases, key-value/cache stores, vector stores, registries, identity resources, and network policy. That visibility lets operators own lifecycle, monitoring, backups, quota, audit, and decommissioning.

---

## Operator View

When reviewing a `Datalab`, start with these questions:

- Who is allowed to access the workspace, and which identity layer enforces it?
- What state will persist after a session stops or the lab is deleted?
- Which credentials and managed services are exposed to workspace code?
- Is Kubernetes API access needed, and should it be namespace-scoped or vcluster-scoped?
- Is external egress broad, blocked, or routed through another control?
- Which parts are backed up, monitored, upgraded, and retired by platform processes?

The sections below map those governance questions to the fields users and engineers see in the `Datalab` spec.

## Concepts

### Sessions
A `Datalab` claim may declare one or more `spec.sessions`. A session is the named workspace identity for a user or workflow. It owns a durable home PVC and may also have a live Educates runtime.

!!! note "Multiple started sessions"

    A single `Datalab` can have multiple sessions started at the same time. This supports patterns such as a default human workspace plus a separate analysis, automation, or agent workspace. Each started session gets its own runtime and durable workspace PVC, while shared Datalab-level credentials and managed services remain operator-visible.

- Each `spec.sessions` entry declares a session by `name`. `state` defaults to `started`.
- `state: started` creates the **WorkshopSession** runtime for that session and mounts the session PVC as the home workspace.
- `state: stopped` keeps the declared session and its PVC, but does not create the **WorkshopSession** runtime. Switching back to `started` reuses the same workspace PVC.
- If no sessions are given, no declared session PVC or runtime is pre-created. The shared runtime namespace and non-session resources can still be reconciled and tested without a `WorkshopSession`.

Sessions can also be patched into the spec later if needed.

### Persistence

Each declared `Datalab` session is equipped with a **persistent volume** for storing files, in addition to the connected object storage. This ensures that user data and session state are preserved even if the workshop pod is restarted, rescheduled by Kubernetes, or intentionally stopped through `state: stopped`. Installing code libraries, handling metadata, or working with Git repositories often generates many small files that may be updated frequently. A storage class providing **NFS-like capabilities** is usually a good fit for these kinds of workloads, **object storage** abstractions are not.

Provider Datalab creates a stable PVC per declared session, including sessions with `state: stopped`, in the Educates workshop namespace and configures Educates to use that claim as the `/home/eduk8s` workspace volume. The size comes from `spec.quota.storage`, and `spec.persistence.storageClassName` may select a StorageClass subject to the operator allowlist in `EnvironmentConfig.data.storageClasses.allowed`.

When `EnvironmentConfig.data.storageClasses.allowed` is non-empty, a requested `storageClassName` is used only if it appears in that list; otherwise Provider Datalab uses the first allowed class. If the list is omitted or empty, any requested class is allowed and an omitted `storageClassName` lets Kubernetes use the cluster default.

For operators, this is the responsibility boundary. Session PVCs are useful for workspace state and many-small-file workloads, but they are not a replacement for managed data services. If data must survive upgrades, disaster recovery events, or independent service lifecycles, use a managed database, a bucket provisioned outside Provider Datalab, or another store with a clear backup policy.

### Database

Many Datalab workloads require a **stateful database** in addition to files and object storage, for example metadata catalogs or application backends.

Instead of running databases inside sessions, Datalabs attach to a **platform-managed database cluster**. The platform creates **logical databases inside that cluster** and provisions credentials automatically.

```yaml
spec:
  databases:
    pg0:
      names:
      - dev
      - prod
      storage: 1Gi
      backupStorage: 3Gi
```

- `pg0` - target **database cluster** managed by the platform
- `names` - logical databases created inside the cluster
- `storage` - persistent storage allocation
- `backupStorage` - space reserved for backups

The platform automatically:

- creates databases and users
- stores credentials in a Secret
- injects connection details into sessions
- configures backups according to the operator-managed database setup
- keeps data independent from session lifecycle

This keeps **compute ephemeral** while **database state remains durable** and reviewable by the platform team.

If a Kubernetes gateway service is running in the cluster and enabled in the global configuration, the database **can also be exposed externally**. In that case, corresponding environment variables such as the external hostname or external URL are injected into the session as well.

For each declared PostgreSQL host, Provider Datalab also exposes host-scoped aliases in the generated `<datalab>-datalab` Secret. For example, `pg0` receives variables such as `POSTGRES_PG0_HOST`, `POSTGRES_PG0_PORT`, `POSTGRES_PG0_DATABASES`, `POSTGRES_PG0_DEV_URL`, and, when gateway exposure is configured, `POSTGRES_PG0_DEV_URL_EXTERNAL`.

> Note: The Postgres endpoint is exposed through a gateway `TLSRoute`, which requires immediate TLS with SNI (direct TLS). The PostgreSQL server and libpq-based clients (e.g. psql, psycopg) fully support this. However, some non-libpq drivers such as asyncpg do not yet implement this negotiation correctly and may fail during connection setup.

### Document, Cache, and Vector Stores

For non-relational workloads, a Datalab can also provision optional document, cache, and vector stores:

```yaml
spec:
  documentStores:
    prod:
      storage: 1Gi
  cacheStores:
    prod:
      storage: 1Gi
  vectorStores:
    prod:
      storage: 1Gi
```

- `documentStores` provisions `MongoDBCommunity` resources (`mongodbcommunity.mongodb.com/v1`).
- `cacheStores` provisions Redis resources (`redis.redis.opstreelabs.in/v1beta2`).
- `vectorStores` provisions `QdrantCluster` resources (`qdrant.io/v1alpha1`).
- Access credentials are created as namespaced Secrets with predictable names:
  - Mongo: `<store>-mongodb-auth` (key: `password`)
  - Redis: `<store>-redis-auth` (key: `password`)
  - Qdrant: `<store>-qdrant-auth` (keys: `apiKey`, `readApiKey`)

Provider Datalab also exposes connection details through the generated `<datalab>-datalab` Secret, which sessions import as environment variables. For a store key such as `prod`, the session receives variables such as `MONGO_PROD_URI`, `REDIS_PROD_URL`, and `QDRANT_PROD_URL`, plus split fields for host, port, user, database, and credentials where applicable.

These stores should be visible platform resources, not ad-hoc services hidden inside a user terminal. The `Datalab` claim records that they exist. The underlying operators handle persistence, upgrades, monitoring, and backups. Before enabling them in production, check the backup and restore guarantees of your MongoDB, Redis, or Qdrant operator setup.

### Docker Registry

A Datalab can optionally provide an in-session Docker registry:

```yaml
spec:
  registry:
    enabled: true
    storage: 3Gi
```

This is useful when users need to push and pull images inside the lab. Treat it as workspace-scoped registry storage and an operator-approved capability. If registry contents need backup, retention, scanning, or promotion into a central registry, define that in platform policy before enabling it.

### Authentication

Provider Datalab is a workspace building block. It can wire authentication into the runtime, but the cleaner production pattern is often to delegate authentication to the surrounding platform, especially at ingress.

For the ownership boundary around workspace access, see the
[Security overview](../security/index.md#access-to-a-datalab).

Multiple options are possible:

- Enable built-in runtime authentication. By default, `auth.type = credentials` uses the same credentials that are used to access the connected object-storage buckets for session login. This is a simple basic-auth style option, but it ties workspace users to the credentials known by the Datalab runtime.
- Set `auth.type = delegated` and let another platform component protect access before requests reach the workspace. This does not mean that unauthenticated access is required; it means authentication is delegated to another layer, such as the Kubernetes ingress controller.

Delegating authentication is often more flexible because users accessing a workspace do not necessarily have to exist in the same identity model used by the Datalab composition. For example, NGINX Ingress can call a shared `oauth2-proxy`, while APISIX can enforce OIDC directly with its `openid-connect` plugin, optionally combined with `keycloak-authz` or the OPA plugin for authorization.

Those controller-specific settings should be added by platform policy instead of being repeated in every Datalab. Kyverno is one option, but the same result can be achieved with a mutating admission webhook, GitOps post-processing, or any other automation that consistently targets the generated Educates Ingress resources. In all examples below, the Datalab environment keeps `auth.type: delegated`; the protection is established externally at the ingress layer.

??? info "Generated workshop session resources"

    For a Datalab named `s-jane` with a `default` session and `ingress.domain: lab.acme.org`, Educates creates session ingress hosts such as:

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

    Provider Datalab also creates a confidential Keycloak client named after the Datalab. For `s-jane`, the generated client includes redirect and web-origin entries for the workspace root and each declared session host:

    ```text
    https://s-jane.lab.acme.org/*
    https://s-jane-default.lab.acme.org/*
    https://editor-s-jane-default.lab.acme.org/*
    https://s-jane-default-editor.lab.acme.org/*
    https://data-s-jane-default.lab.acme.org/*
    https://s-jane-default-data.lab.acme.org/*
    http://localhost:*
    ```

    This allows ingress-layer OIDC implementations, such as APISIX `openid-connect`, to reuse the Datalab-owned Keycloak client without an extra Keycloak mutation policy. Provider Datalab publishes the credentials for OIDC consumers as runtime Secret `s-jane-oauth2-client` with data keys `client_id` and `client_secret`. The client keeps human and machine authority separate. Browser users receive `ws_access` or `ws_admin` through Datalab groups. Client-credentials automation uses the same confidential client but receives only the service-account role `ws_api`.

    To call Workspace API with the client-credentials flow from the runtime namespace, read `client_id` and `client_secret` from `<datalab>-oauth2-client`, request a token with `grant_type=client_credentials`, then send that access token to Workspace API.

??? example "Shared delegated-auth environment configuration"

    Both nginx and APISIX examples use delegated auth at the Datalab layer. Change `ingress.class` to match the ingress controller you operate.

    ```yaml
    apiVersion: apiextensions.crossplane.io/v1beta1
    kind: EnvironmentConfig
    metadata:
      name: datalab
    data:
      iam:
        realm: acme
      auth:
        type: delegated
      ingress:
        class: apisix # use "nginx" for the nginx example
        domain: lab.acme.org
        secret: workspace-tls
      storage:
        endpoint: https://s3.acme.org
        provider: Other
        region: acme
        force_path_style: "true"
        secretNamespace: workspace
        type: s3
    ```

    The Educates installation must use the same ingress class, domain, and TLS secret. For example, an APISIX-based deployment would set:

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

??? example "NGINX Ingress with oauth2-proxy"

    With NGINX Ingress, the usual pattern is an externally deployed `oauth2-proxy` instance and NGINX external-auth annotations on the generated workshop-session ingresses.

    In this model, `oauth2-proxy` normally uses its own OAuth client, for example with redirect URI:

    ```text
    https://auth.lab.acme.org/oauth2/callback
    ```

    The Datalab-generated Keycloak clients are still useful for direct OIDC ingress controllers, but a central `oauth2-proxy` does not need one client per Datalab unless you intentionally deploy it that way.

    ```yaml
    apiVersion: kyverno.io/v1
    kind: ClusterPolicy
    metadata:
      name: protect-workshop-sessions-nginx
    spec:
      admission: true
      background: false
      rules:
      - name: add-oauth2-proxy-annotations
        match:
          any:
          - resources:
              kinds:
              - Ingress
              selector:
                matchLabels:
                  training.educates.dev/application: workshop
                  training.educates.dev/component: session
        preconditions:
          all:
          - key: "{{ request.object.spec.ingressClassName || '' }}"
            operator: Equals
            value: nginx
          - key: "{{ (request.object.spec.rules || [])[?host != null && ends_with(host, '.lab.acme.org')] | length(@) }}"
            operator: GreaterThan
            value: 0
        mutate:
          patchStrategicMerge:
            metadata:
              annotations:
                +(nginx.ingress.kubernetes.io/auth-url): "https://auth.lab.acme.org/oauth2/auth"
                +(nginx.ingress.kubernetes.io/auth-signin): "https://auth.lab.acme.org/oauth2/start?rd=https://$host$escaped_request_uri"
                +(nginx.ingress.kubernetes.io/auth-response-headers): "Authorization,X-Auth-Request-User,X-Auth-Request-Email,X-Auth-Request-Preferred-Username"
    ```

    Configure `oauth2-proxy` with a cookie domain that covers the workshop hosts, for example `.lab.acme.org`, and restrict allowed redirect domains to the same boundary.

??? example "APISIX Ingress with openid-connect and OPA"

    With APISIX, the ingress controller can enforce OIDC directly. For authorization, add the APISIX OPA plugin to the same `ApisixPluginConfig` and point it at a policy that validates workspace access. This pattern mirrors the EOEPCA deployment, adapted to `acme.org`.

    The APISIX `openid-connect` plugin must use the generated confidential client secret. Use APISIX Ingress Controller's plugin-level `secretRef` to use the automatically generated `<datalab>-oauth2-client` Secret in the runtime namespace with APISIX-compatible `client_id` and `client_secret` keys.

    If the OPA policy checks Keycloak client roles in `resource_access`, request the `roles` scope in the APISIX `openid-connect` plugin. The access token must also be made available as an `Authorization: Bearer ...` header so the APISIX OPA plugin can pass it to OPA for policy evaluation. Without the `roles` scope, Keycloak may issue a valid access token that contains identity claims but not the client-role claims needed by the policy.

    Kyverno needs permission to create `ApisixPluginConfig` resources in the generated session namespaces:

    ```yaml
    apiVersion: rbac.authorization.k8s.io/v1
    kind: ClusterRole
    metadata:
      name: kyverno:workspace-session-apisix-pluginconfigs
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

    The Kyverno policy does not need `secrets/get`: it writes APISIX `secretRef` to the generated plugin config. The APISIX ingress-controller service account must be allowed to read the generated `<datalab>-oauth2-client` Secret in the runtime namespace.

    The policy generates one APISIX plugin config per session namespace and annotates the matching workshop ingress to use it:

    ```yaml
    apiVersion: kyverno.io/v1
    kind: ClusterPolicy
    metadata:
      name: protect-workshop-sessions-apisix
    spec:
      admission: true
      background: false
      rules:
      - name: generate-apisix-oidc-plugin-config
        match:
          any:
          - resources:
              kinds:
              - Ingress
              selector:
                matchLabels:
                  training.educates.dev/application: workshop
                  training.educates.dev/component: session
        preconditions:
          all:
          - key: "{{ request.object.spec.ingressClassName || '' }}"
            operator: Equals
            value: apisix
          - key: "{{ (request.object.spec.rules || [])[?host != null && ends_with(host, '.lab.acme.org')] | length(@) }}"
            operator: GreaterThan
            value: 0
          - key: "{{ request.object.metadata.labels.\"training.educates.dev/environment.name\" || '' }}"
            operator: NotEquals
            value: ""
        generate:
          apiVersion: apisix.apache.org/v2
          kind: ApisixPluginConfig
          name: "workspace-oidc-{{ request.object.metadata.labels.\"training.educates.dev/environment.name\" }}"
          namespace: "{{ request.namespace }}"
          synchronize: false
          data:
            metadata:
              labels:
                training.educates.dev/application: workshop
                training.educates.dev/component: session
                training.educates.dev/environment.name: "{{ request.object.metadata.labels.\"training.educates.dev/environment.name\" }}"
            spec:
              plugins:
              - name: openid-connect
                enable: true
                secretRef: "{{ request.object.metadata.labels.\"training.educates.dev/environment.name\" }}-oauth2-client"
                config:
                  discovery: "https://iam-auth.acme.org/realms/acme/.well-known/openid-configuration"
                  use_jwks: true
                  bearer_only: false
                  scope: openid profile email roles
                  session:
                    secret: "{{ random('[A-Za-z0-9]{32}') }}"
                  access_token_in_authorization_header: true
                  set_access_token_header: true
                  set_id_token_header: false
                  set_userinfo_header: false
                  set_refresh_token_header: false
              - name: opa
                enable: true
                config:
                  host: http://opa.iam:8181
                  policy: example/workspace/wsui
      - name: add-apisix-oidc-plugin-config
        match:
          any:
          - resources:
              kinds:
              - Ingress
              selector:
                matchLabels:
                  training.educates.dev/application: workshop
                  training.educates.dev/component: session
        preconditions:
          all:
          - key: "{{ request.object.spec.ingressClassName || '' }}"
            operator: Equals
            value: apisix
          - key: "{{ (request.object.spec.rules || [])[?host != null && ends_with(host, '.lab.acme.org')] | length(@) }}"
            operator: GreaterThan
            value: 0
          - key: "{{ request.object.metadata.labels.\"training.educates.dev/environment.name\" || '' }}"
            operator: NotEquals
            value: ""
        mutate:
          patchStrategicMerge:
            metadata:
              annotations:
                +(k8s.apisix.apache.org/plugin-config-name): "workspace-oidc-{{ request.object.metadata.labels.\"training.educates.dev/environment.name\" }}"
    ```

    The `openid-connect` plugin gets `client_id` and `client_secret` from the generated runtime Secret referenced by `secretRef`. Because Provider Datalab creates the matching confidential Keycloak client, redirect URIs, and runtime OAuth2 credential Secret, no additional Keycloak mutation is required for declared sessions. The `opa` plugin should use a policy that derives the workspace from the requested host or client and allows browser requests only for platform administrators or users with generated workspace roles such as `ws_access` or `ws_admin`. Client-credentials tokens should be handled as machine/API tokens and accepted only where the generated `ws_api` role is intended.

    The session secret is generated when Kyverno creates the `ApisixPluginConfig`. `synchronize: false` keeps the generated object stable; if you intentionally change the plugin template for existing sessions, recreate the generated plugin config or restart the session so Kyverno can generate a fresh one.

    The ID token, userinfo, and refresh token forwarding flags are disabled by default. The access token is placed in the `Authorization` header for the APISIX OPA plugin, matching the common APISIX plugin chain where `openid-connect` runs before `opa`. If you do not want the upstream workspace application to receive that header, add an APISIX header-rewrite or equivalent platform policy after authorization to strip it before proxying upstream.

Other ingress controllers follow the same delegated pattern: set `auth.type: delegated`, match the generated workshop session ingresses by label and domain, and attach the controller-specific authentication policy.

Full example manifests are available in the repository:

- [examples/ingress-protection/nginx-oauth2-proxy-workshop-session-protection.yaml](https://github.com/versioneer-tech/provider-datalab/blob/main/examples/ingress-protection/nginx-oauth2-proxy-workshop-session-protection.yaml)
- [examples/ingress-protection/apisix-workshop-session-protection.yaml](https://github.com/versioneer-tech/provider-datalab/blob/main/examples/ingress-protection/apisix-workshop-session-protection.yaml)

Keycloak-managed access is supported. When it is used, the composition automatically provisions the confidential Keycloak client, runtime OAuth2 credential Secret, groups, roles, role scope mappings, group role bindings, service-account role binding, and memberships needed for the workspace.

### Files and the Workshop Tab
The `spec.files` array is optional.

- When empty or omitted, **no workshop tab** is rendered in the Educates UI.
- When at least one source is defined, workshop and/or data content is mounted and the tab is enabled.

Supported sources:

- **OCI image** (`spec.files[].image`)
- **Git repository** (`spec.files[].git`)
- **HTTP(S) download** (`spec.files[].http`)

Filters (`includePaths`, `excludePaths`, `newRootPath`, `path`) control what ends up visible.

### vcluster toggle
`spec.vcluster` is a boolean flag.
- `true` → the datalab provisions a vcluster for runtime isolation.
- `false` → workloads run directly in the namespace.

### Storage Secret
A Datalab requires credentials to an S3-compatible storage system. Provider Datalab does not create the bucket. Create it manually, through your platform process, or with [Provider Storage](https://provider-storage.versioneer.at/).

Provider Datalab reads the credentials from a Kubernetes Secret named via `spec.secretName`, or by the `Datalab` name when `spec.secretName` is omitted. The Secret lives in `EnvironmentConfig.data.storage.secretNamespace`, which is usually the same namespace as the `Datalab` claim.

This secret must include at least `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`. The endpoint and provider are defined in `EnvironmentConfig.data.storage`.

### Security and Access Policy
The `spec.security` section controls access permissions and runtime privilege level for sessions.

Key fields:

- `policy` — defines Pod Security Standard (`restricted`, `baseline`, `privileged`).
  - `privileged` enables Docker-in-Docker with 20 Gi of local storage.
- `kubernetesAccess` — whether a Kubernetes service account token is mounted inside the session.
- `kubernetesRole` — defines in-namespace RBAC level (`admin`, `edit`, `view`).
- `externalEgress` — controls generated external egress for all sessions and
  workloads in the runtime namespace.

For the operator security model, workspace sandbox boundaries, and recommended
policy bundles, see the [Security](../security/index.md) section.

When `externalEgress` is omitted, Provider Datalab uses
`EnvironmentConfig.data.defaults.security.externalEgress` and then the hard
default `true`. With `externalEgress: false`, the generated policies only allow
namespace-local Pod egress. With external egress enabled, Provider Datalab
excludes the configured pod and service CIDRs from broad external egress.
Cross-namespace traffic still needs a separate operator-owned NetworkPolicy.

### Resource Quotas
The `spec.quota` section allows per-Datalab overrides of default compute and storage budgets.

- `memory` — memory allocation per session (default 2 Gi).
- `storage` — persistent volume size (default 1 Gi).
- `budget` — Educates resource budget profile (`small`, `medium`, `large`, `x-large`, etc.).

When unspecified, defaults from the EnvironmentConfig apply.

| Budget    | CPU   | Memory |
|-----------|-------|--------|
| small     | 1000m | 1Gi    |
| medium    | 2000m | 2Gi    |
| large     | 4000m | 4Gi    |
| x-large   | 8000m | 8Gi    |
| xx-large  | 8000m | 12Gi   |
| xxx-large | 8000m | 16Gi   |

### Identity and Keycloak Resources
When Keycloak-managed access is used, users listed under `spec.users` must already exist in Keycloak.
When a Datalab is created for that pattern, the composition automatically provisions the required **Keycloak resources**:

- **Groups** for the Datalab and Datalab administrators. The regular group is named after the Datalab, and the administrator group uses `<datalab>-admin`.
- **Group memberships** for the listed users. Users listed in `spec.users` join the regular group; selected administrators also join the admin group.
- A dedicated confidential **OAuth2 client** named after the Datalab. It allows authorization-code browser login and client credentials, while implicit, device, and direct access grants are disabled.
- A runtime **Secret** named `<datalab>-oauth2-client`, with data keys `client_id` and `client_secret`, generated by Provider Datalab in the runtime workshop namespace for ingress controllers and client-credentials automation.
- User, admin, and machine/API **roles**: `ws_access`, `ws_admin`, and `ws_api`.
- Role scope mappings for the generated client because `fullScopeAllowed` is disabled. Tokens only get the generated workspace client roles that are explicitly mapped.
- Optional access-token audience mappers. Provider Datalab adds one mapper for each value in `EnvironmentConfig.data.iam.extraAudiences`; when the field is omitted or empty, no extra audience mapper is created. The central Workspace API OAuth client also needs to emit the same Workspace API audience when that audience is required, but it is managed by the realm or platform identity setup rather than by Provider Datalab.
- Group role bindings for `ws_access` and `ws_admin`, plus a service-account role binding for `ws_api`.

This ensures that authentication and authorization are consistently enforced across the runtime and UI. If authentication is delegated to the ingress or another platform component, the identities allowed through that outer layer are managed by that component and do not necessarily have to be users in the Datalab Keycloak realm. The generated runtime OAuth2 client Secret is still a workspace machine credential and should be readable only by users or automation that may mint client-credentials tokens for that Datalab. The Workspace API gateway should treat those client-credentials tokens as machine tokens and require the configured Workspace API audience; Workspace API authorization should require the `ws_api` client role, not user group membership.

The runtime workshop namespace `<datalab>-oauth2-client` Secret is the supported consumer contract for ingress-side resources such as APISIX and other controller-side policy.

---

## Example: Joe (no session by default)

```yaml
# Joe gets a personal datalab s-joe with no pre-created session.
# He must explicitly declare and start a session himself; nothing is running by default.
# No vcluster is provisioned and no workshop files are attached.
# Credentials to storage are expected to exist in a secret "s-joe" in the same namespace.
# A Keycloak group, role, and client are created; user "joe" must exist in Keycloak.
apiVersion: pkg.internal/v1beta2
kind: Datalab
metadata:
  name: s-joe
spec:
  users:
  - joe
  secretName: s-joe
```

- Joe’s Datalab exists but is idle until he launches a session; the Data tab's
  `package-r` runtime starts with the session when `spec.data.enabled` is true.
- Useful for lightweight, on-demand environments.
- Keycloak ensures Joe is authorized to access his workspace.

---

## Example: Jeff, Jim, and Jane (shared store validation, no Kubernetes API access)

```yaml
# Jeff (owner), Jim (admin) and Jane (user) share a datalab s-jeff with no pre-created session.
# This is the canonical shared store-validation example: the lab stays sessionless by default.
# The lab does not use a vcluster and has no workshop files.
# Credentials to storage are expected to exist in a secret "s-jeff" in the same namespace.
# A Keycloak group, role, and client are created; users "jeff", "jim" and "jane" must exist in Keycloak.
# This configuration keeps the default baseline security policy:
# - Docker registry is disabled for this shared example.
# - Session quota: increased to 6 Gi memory, 1 Gi storage, budget class "x-large".
# - Kubernetes API access is disabled (kubernetesAccess=false).
# The data component for the object storage mount and browser UI is disabled.
# Additionally, two PostgreSQL databases are provisioned for the lab: "prod" and "dev".
# Additionally, one MongoDB-backed document store is provisioned:
# - prod with 1 Gi storage
# Additionally, one Redis-backed cache store is provisioned:
# - prod with 1 Gi storage
# Additionally, one Qdrant-backed vector store is provisioned:
# - prod with 1 Gi storage
# Access credentials are generated as secrets in the runtime namespace:
# - MongoDB: <store>-mongodb-auth
# - Redis: <store>-redis-auth
# - Qdrant: <store>-qdrant-auth
apiVersion: pkg.internal/v1beta2
kind: Datalab
metadata:
  name: s-jeff
spec:
  users:
    - jeff
    - jim
    - jane
  userOverrides:
    jim:
      grantedAt: "2025-01-10T19:00:00Z"
      role: admin
  secretName: s-jeff
  sessions: []
  vcluster: false
  data:
    enabled: false
  quota:
    memory: 6Gi
    storage: 1Gi
    budget: x-large
  files: []
  security:
    kubernetesAccess: false
    externalEgress: false
  registry:
    enabled: false
    storage: 3Gi
  documentStores:
    prod:
      storage: 1Gi
  cacheStores:
    prod:
      storage: 1Gi
  vectorStores:
    prod:
      storage: 1Gi
  databases:
    pg0:
      names:
      - dev
      - prod
      storage: 1Gi
      backupStorage: 3Gi
```

- No `WorkshopSession` is pre-created for this shared example. The runtime namespace and backing services can be validated without a session pod.
- Runs with the default **baseline** security policy.
- **No Kubernetes API access** is granted inside the environment. The shared example leaves the registry disabled.
- Access is secured through the corresponding Keycloak group and role.

---

## Example: Jane (isolated vcluster with admin role and higher quota)

```yaml
# Jane runs a datalab s-jane with a default session automatically created.
# That session will run permanently until stopped by the operator,
# and a dedicated vcluster is provisioned for runtime isolation.
# No workshop files are attached. Credentials to storage are expected
# to exist in a secret "s-jane" in the same namespace.
# A Keycloak group, role, and client are created; user "jane" must exist in Keycloak.
# This configuration explicitly overrides default resource quotas and security settings:
# - Security policy: "privileged" → automatically enables Docker with 20 Gi workspace storage.
# - Docker registry is enabled with 3 Gi storage.
# - Session quota: increased to 4 Gi memory, 40 Gi storage, budget class "x-large".
# - Kubernetes role: elevated to "admin" for full namespace permissions.
# The data component for the object storage mount and browser UI is configured as readonly.
# Additionally, one PostgreSQL database is provisioned for the lab: "analytics".
apiVersion: pkg.internal/v1beta2
kind: Datalab
metadata:
  name: s-jane
spec:
  users:
    - jane
  secretName: s-jane
  sessions:
    - name: default
      state: started
  vcluster: true
  data:
    readOnlyMount: true
  quota:
    memory: 4Gi
    storage: 40Gi
    budget: x-large
  registry:
    enabled: true
    storage: 3Gi
  security:
    policy: privileged
    kubernetesRole: admin
  databases:
    pg0:
      names:
      - analytics
      storage: 1Gi
      backupStorage: 3Gi
```

- Jane’s workloads run inside an **isolated virtual cluster** (`vcluster: true`).
- The lab also runs in **privileged** mode, which enables Docker with 20 Gi of session-local workspace storage.
- The **admin role** grants full control within her namespace/vcluster.
- This is the registry-enabled example, so session-backed registry behavior can be validated here.
- Suitable for trusted advanced development or testing that really needs full Kubernetes control.
- Treat this as an operator-approved exception because it combines privileged runtime, registry writes, and elevated Kubernetes authority.
- Keycloak enforces role-based access protection for this lab when Keycloak-managed access is used.

---

## Example: John (with Git-based workshop files)

```yaml
# John has a datalab s-john with a default session automatically created.
# That session will run permanently until stopped by the operator.
# No vcluster is provisioned. Workshop and data files are pulled from Git,
# enabling the workshop tab in the Educates UI.
# The analysis session is declared but stopped, so it keeps its workspace PVC
# without creating a runtime.
# Credentials to storage are expected in a secret "s-john" in the same namespace.
# A Keycloak group, role, and client are created; user "john" must exist in Keycloak.
apiVersion: pkg.internal/v1beta2
kind: Datalab
metadata:
  name: s-john
spec:
  users:
  - john
  secretName: s-john
  sessions:
  - name: default
  - name: analysis
    state: stopped
  vcluster: false
  files:
  - git:
      url: https://github.com/versioneer-tech/datalab-example
      ref: origin/main
    includePaths:
    - /workshop/**
    - /data/**
    - /README.md
    path: .
```

- Preloads workshop materials from Git.
- Activates the workshop tab in the UI for guided exercises.
- Keycloak ensures only John has access to this environment and tooling.

---

## Verifying Provisioning

Once a `Datalab` claim has been applied, you can verify that the provisioning worked.

### Check Composite Status

```bash
kubectl get datalabs -n workspace
```

You should see all Datalabs `READY=True` once reconciliation is complete:

```
NAME       SYNCED   READY   COMPOSITION       AGE
s-joe      True     True    datalab-educates  2m
s-jeff     True     True    datalab-educates  2m
s-jane     True     True    datalab-educates  2m
s-john     True     True    datalab-educates  2m
```

Inspect details:

```bash
kubectl describe datalab s-jeff -n workspace
```

Look for conditions like `Ready=True` and any event messages.

### Find the Storage Secret

Each Datalab references a storage **Secret** named by `spec.secretName`, or by the `Datalab` name when `spec.secretName` is omitted. The Secret lives in `EnvironmentConfig.data.storage.secretNamespace`, which is usually the same namespace as the `Datalab` claim.
For example, the claim `s-jeff` with `secretName: s-jeff` requires a Secret named `s-jeff`.

```bash
kubectl get secret s-jeff -n workspace -o yaml
```

Decode credentials (AWS-style):

```bash
kubectl get secret s-jeff -n workspace -o jsonpath='{.data.AWS_ACCESS_KEY_ID}' | base64 -d; echo
kubectl get secret s-jeff -n workspace -o jsonpath='{.data.AWS_SECRET_ACCESS_KEY}' | base64 -d; echo
```

### Connect to Databases

Starting with version 0.3.0, databases can be provisioned on a dedicated PostgreSQL host. The current baseline expects Crunchy PostgreSQL Operator `v6.0.x` and renders `PostgresCluster` as `postgres-operator.crunchydata.com/v1`. Optionally, these databases can also be exposed externally using a Gateway API `TLSRoute`, enabling secure access from outside the cluster. External exposure requires a Layer-4 capable Gateway implementation, such as Envoy Gateway or your cluster-validated equivalent, with `TLSRoute` served as `gateway.networking.k8s.io/v1`. The bundled Gateway API `v1.5.1` CRDs serve `TLSRoute` as `v1`.

All additional users are created as regular database roles with limited privileges. Full administrative access is provided through the built-in `postgres` superuser account. This account can create extensions, manage schemas, and grant permissions to other users as needed.

Database credentials are managed by the PostgreSQL operator and stored as Kubernetes Secrets. To locate the credentials for database users, look for Secrets matching:
`*-pguser-*`. These Secrets contain the connection details required to authenticate against the corresponding PostgreSQL roles.

---

## Summary

- A `Datalab` defines users, sessions, optional vcluster, quotas, and security policies.
- A `Datalab` can also define platform-managed databases, document stores, key-value/cache stores, vector stores, and registry storage.
- Security controls combine **Pod Security Standards**, **Kubernetes roles**, **NetworkPolicies**, and **Docker privilege** toggles.
- Each Datalab requires a storage credential Secret.
- Durable data services remain visible to operators, which is the basis for backup, restore, monitoring, and lifecycle responsibility.
- Object-storage buckets are created outside Provider Datalab, for example with Provider Storage; Provider Datalab consumes the resulting credentials.
- For Keycloak-managed access, users must already exist in Keycloak; the Datalab provisions groups, memberships, a client, roles, and role bindings.
- For delegated access, `auth.type = delegated` leaves authentication to the ingress layer or another platform component.
- Sessions may be started for live work or stopped while keeping their workspace PVC.
- Workshop files enable the Educates UI workshop tab.
- Check `kubectl get datalabs` for readiness and confirm Secret and Keycloak resource creation where applicable.
