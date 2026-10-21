# Provider Datalab – Usage & Concepts

This guide explains how to configure and use a Datalab after installation.

Users request sessions and data services through the `Datalab` spec. The platform team configures shared services, access rules, resource limits, and backups.

---

## Operator View

When reviewing a `Datalab`, start with these questions:

- Who is allowed to access the workspace, and which identity layer enforces it?
- What state will persist after a session stops or the lab is deleted?
- Which credentials and managed services are exposed to workspace code?
- Is Kubernetes API access needed, and should it be namespace-scoped or vCluster-scoped?
- Is external egress broad, blocked, or routed through another control?
- Which parts are backed up, monitored, upgraded, and retired by platform processes?

The sections below explain the related fields in the `Datalab` spec.

## Concepts

### Sessions

A `Datalab` claim may declare one or more `spec.sessions`. In the current API,
a Datalab session is a named, durable workspace such as `default` or
`analysis`. It owns a home PVC and may have a live Educates runtime.

!!! note "Multiple started sessions"

    A single `Datalab` can have multiple sessions started at the same time.
    This supports patterns such as `default` and `analysis`. Each started
    session gets its own workspace Pod and persistent workspace PVC. Sessions
    share the Datalab's credentials and managed services.

- Each `spec.sessions` entry declares a session by `name`. `state` defaults to `started`.
- `state: started` creates the Educates `WorkshopSession` for that Datalab
  session. Educates creates the replaceable workspace Pod and mounts the
  session PVC as its home workspace.
- `state: stopped` keeps the declared session and its PVC, but does not create
  the `WorkshopSession`. Switching back to `started` selects the same
  workspace PVC.
- If no sessions are given, no declared session PVC or runtime is pre-created. The shared runtime namespace and non-session resources can still be reconciled and tested without a `WorkshopSession`.

Sessions can also be patched into the spec later if needed.

### Persistence

Each declared `Datalab` session is equipped with a **persistent volume** for
storing files, in addition to the connected object storage. The workspace Pod
is replaceable and mounts that volume at `/home/eduk8s`. The PVC remains
declared when the session uses `state: stopped`, although live lifecycle tests
are still needed for the complete stop, start, and recovery path. Installing
code libraries, handling metadata, or working with Git repositories often
generates many small files that may be updated frequently. A storage class
providing **NFS-like capabilities** is usually a good fit for these kinds of
workloads; **object storage** is not.

Provider Datalab creates a stable PVC per declared session, including sessions with `state: stopped`, in the Educates workshop namespace and configures Educates to use that claim as the `/home/eduk8s` workspace volume. The size comes from `spec.quota.storage`, and `spec.persistence.storageClassName` may select a StorageClass subject to the operator allowlist in `EnvironmentConfig.data.storageClasses.allowed`.

When `EnvironmentConfig.data.storageClasses.allowed` is non-empty, a requested `storageClassName` is used only if it appears in that list; otherwise Provider Datalab uses the first allowed class. If the list is omitted or empty, any requested class is allowed and an omitted `storageClassName` lets Kubernetes use the cluster default.

Use session PVCs for workspace files. For data that needs separate backups, recovery, or maintenance, use a managed database, an object-storage bucket, or another store with a defined backup policy.

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

Database data remains available when a session stops or its workspace Pod is replaced.

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

The `Datalab` claim records which stores to create. The installed operators manage them. Before enabling a store in production, check how your operator setup handles storage, upgrades, monitoring, backups, and restore.

### Docker Registry

A Datalab can optionally provide an in-session Docker registry:

```yaml
spec:
  registry:
    enabled: true
    storage: 3Gi
```

This is useful when users need to push and pull images inside the lab. Treat it as workspace-scoped registry storage and an operator-approved capability. If registry contents need backup, retention, scanning, or promotion into a central registry, define that in platform policy before enabling it.

### Data and Sharing

The Data service (`package-r`) gives you access to your Datalab's object-storage
buckets without a compute session. When the platform enables a permanent Data
address, you can browse and share data without declaring or starting a
session. A running session's Data tab opens the same service. The file browser
requires sign-in.

Use the Data service to share data with other teams on the same platform.
To reach people outside the platform, including the wider public, send
presigned download URLs for individual files or public share links for
folders. Recipients do not need a Datalab account. The public share is
described below.

#### Sharing Data with the World

Use the public share to publish datasets, example files, or results that
others can use. Put the files in your Datalab's `public` folder and share the
public link. Anyone can browse and download them without a Datalab account or
sign-in.

In the Data browser, this folder is at `<datalab>/public`: the `public` folder
in the bucket named after your Datalab. For example, a file at
`s-jane/public/results.csv` is part of the public share for `s-jane`.
This is the folder connected to the default public share; a folder named
`public` elsewhere is not automatically shared.

Public sharing uses the permanent Data address, which the platform operator
must enable. You can place files in the folder through the Data browser when
write access is allowed, or through your usual storage tools.

### Authentication

The platform ingress layer handles session authentication and authorization. Configure it to protect access to each Datalab with components such as NGINX Ingress and `oauth2-proxy` or APISIX and the `openid-connect` plugin.

For the ownership boundary around workspace access, see the
[Security overview](../security/index.md#access-to-a-datalab).

Users listed in `spec.users` must exist in the configured Keycloak realm. APISIX can combine `openid-connect` with `keycloak-authz` or the OPA plugin for authorization.

Those controller-specific settings should be added by platform policy instead of being repeated in every Datalab. Kyverno is one option, but the same result can be achieved with a mutating admission webhook, GitOps post-processing, or any other automation that consistently targets the generated Educates Ingress resources. In all examples below, protection is established externally at the ingress layer.

The CEL policies in this section require Kyverno `v1.19.1` or later. Kyverno
is required only when you use these policy examples. Provider Datalab itself
does not require Kyverno.

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

    Provider Datalab also creates a confidential Keycloak client named after the Datalab. For `s-jane`, the generated client includes redirect and web-origin entries for the Datalab root and each declared session host:

    ```text
    https://s-jane.lab.acme.org/*
    https://s-jane-default.lab.acme.org/*
    https://editor-s-jane-default.lab.acme.org/*
    https://s-jane-default-editor.lab.acme.org/*
    https://data-s-jane-default.lab.acme.org/*
    https://s-jane-default-data.lab.acme.org/*
    http://localhost:*
    ```

    This allows services intentionally owned by `s-jane` to reuse the Datalab-owned Keycloak client without an extra Keycloak mutation policy. Provider Datalab publishes the credentials for direct per-Datalab OIDC consumers and client-credentials automation as runtime Secret `s-jane-oauth2-client` with data keys `client_id` and `client_secret`. Shared browser ingress for many Datalabs can instead use a central platform OAuth client. The generated client keeps human and machine authority separate. Human users receive `ws_access` or `ws_admin` through Datalab groups. Client-credentials automation uses the same confidential client but receives only the service-account role `ws_api`.

    To call a Datalab-owned service with a machine token, read `client_id` and `client_secret` from `<datalab>-oauth2-client`, request a token with `grant_type=client_credentials`, then send that access token to the service. Its policy should require `ws_api` and any configured audience.

??? example "Shared environment configuration"

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

    The Datalab-generated Keycloak clients are still useful for Datalab-owned services or direct per-Datalab OIDC integrations, but a central `oauth2-proxy` does not need one client per Datalab unless you intentionally deploy it that way.

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

    Configure `oauth2-proxy` with a cookie domain that covers the workshop hosts, for example `.lab.acme.org`, and restrict allowed redirect domains to the same boundary.

??? example "APISIX Ingress with openid-connect and OPA"

    With APISIX, the ingress controller can enforce OIDC directly. For authorization, add the APISIX OPA plugin to the same `ApisixPluginConfig` and point it at a policy that validates Datalab access.

    For shared workshop-session browser ingress, prefer a central platform OAuth client such as `datalab-sessions`. The generated `<datalab>-oauth2-client` Secret remains useful for client-credentials automation and for services intentionally owned by one Datalab, but it should not be the default shared browser-ingress credential.

    If the OPA policy checks Keycloak client roles in `resource_access`, request the `roles` scope in the APISIX `openid-connect` plugin. The access token must also be made available as an `Authorization: Bearer ...` header so the APISIX OPA plugin can pass it to OPA for policy evaluation. Without the `roles` scope, Keycloak may issue a valid access token that contains identity claims but not the client-role claims needed by the policy.

    Kyverno needs permission to create `ApisixPluginConfig` resources in the generated session namespaces:

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

    The Kyverno policies below do not need Secret read access because they use
    a central public OAuth client. If your platform uses a confidential central
    client, inject that platform-managed credential with the ingress
    controller's supported Secret mechanism instead of the generated
    per-Datalab runtime Secret.

    The CEL policies generate one APISIX plugin config per session namespace
    and annotate the matching workshop ingress to use it:

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

    The `opa` plugin should use a policy that derives the Datalab from the requested host and allows browser requests only for users with generated Datalab roles such as `ws_access` or `ws_admin`. Client-credentials tokens minted from the generated `<datalab>-oauth2-client` Secret should be handled as machine/API tokens and accepted only where the generated `ws_api` role is intended.

    The session secret is generated when Kyverno creates the
    `ApisixPluginConfig`. Disabled synchronization keeps the generated object
    stable. If you change the plugin template for an existing session, recreate
    the generated plugin config or restart the session so Kyverno can generate
    a new one.

    The ID token, userinfo, and refresh token forwarding flags are disabled by default. The access token is placed in the `Authorization` header for the APISIX OPA plugin, matching the common APISIX plugin chain where `openid-connect` runs before `opa`. If you do not want the upstream workspace application to receive that header, add an APISIX header-rewrite or equivalent platform policy after authorization to strip it before proxying upstream.

For other ingress controllers: match the generated workshop session ingresses by label and domain, and attach the controller-specific authentication policy.

Full example manifests are available in the repository:

- [examples/ingress-protection/nginx-oauth2-proxy-workshop-session-protection.yaml](https://github.com/versioneer-tech/provider-datalab/blob/main/examples/ingress-protection/nginx-oauth2-proxy-workshop-session-protection.yaml)
- [examples/ingress-protection/apisix-workshop-session-protection.yaml](https://github.com/versioneer-tech/provider-datalab/blob/main/examples/ingress-protection/apisix-workshop-session-protection.yaml)

For each Datalab, the composition provisions the confidential Keycloak client, runtime OAuth2 credential Secret, groups, roles, role scope mappings, group role bindings, service-account role binding, and memberships needed for the workspace.

### Files and the Workshop Tab
The `spec.files` array is optional.

- When empty or omitted, **no workshop tab** is rendered in the Educates UI.
- When at least one source is defined, workshop and/or data content is mounted and the tab is enabled.

Supported sources:

- **OCI image** (`spec.files[].image`)
- **Git repository** (`spec.files[].git`)
- **HTTP(S) download** (`spec.files[].http`)

Filters (`includePaths`, `excludePaths`, `newRootPath`, `path`) control what ends up visible.

### vCluster toggle

`spec.vcluster` is a boolean flag.

- `true` → the current Educates Composition enables a vCluster application for
  each started session.
- `false` → workloads run directly in the namespace.

### Storage Secret
A Datalab requires credentials to an S3-compatible storage system. Provider Datalab does not create the bucket. Create it manually, through your platform process, or with [Provider Storage](https://provider-storage.versioneer.at/).

Provider Datalab reads the credentials from a Kubernetes Secret named via `spec.secretName`, or by the `Datalab` name when `spec.secretName` is omitted. The Secret lives in `EnvironmentConfig.data.storage.secretNamespace`, which is usually the same namespace as the `Datalab` claim.

This secret must include at least `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`.
The endpoint and provider are defined in `EnvironmentConfig.data.storage`.
For the Data service, `storage.endpoint` must be reachable from the `package-r`
Pod. Browsers use the Data service to access storage. The file browser
requires sign-in, while public shares can be read without signing in.

### Security and Access Policy
The `spec.security` section controls access permissions and runtime privilege level for sessions.

Key fields:

- `policy` — defines Pod Security Standard (`restricted`, `baseline`, `privileged`).
  - `privileged` enables Docker-in-Docker with 20 Gi of local storage.
- `kubernetesAccess` — whether a Kubernetes service account token is mounted inside the session.
- `kubernetesRole` — defines in-namespace RBAC level (`admin`, `edit`, `view`).
- `externalEgress` — controls generated external egress for all sessions and
  workloads in the runtime namespace. External egress can be restricted at the
  platform level in `EnvironmentConfig` or per workspace in `spec.security`;
  see [Sandbox Security Measures](../security/sandbox-controls.md) for the
  policy details.

Direct S3 requests from `package-r` follow the same Datalab egress policy. Use
`EnvironmentConfig.data.network.internalEgress` for an endpoint in another
runtime namespace, or allow its external address through the external egress
policy.

For the full policy model, see [Sandbox Security Measures](../security/sandbox-controls.md).

### Resource Quotas
The `spec.quota` section allows per-Datalab overrides of default per-session
compute and storage settings.

- `memory` — memory allocation per session (default 2 Gi).
- `storage` — persistent volume size (default 1 Gi).
- `budget` — Educates resource budget profile (`small`, `medium`, `large`, `x-large`, etc.).

When unspecified, values from `EnvironmentConfig.data.defaults.quota` apply.

`spec.overallQuota.storage` controls the aggregate PVC requested-storage quota
in the Datalab environment namespace. It falls back to
`EnvironmentConfig.data.defaults.overallQuota.storage` and then to the hard
default `100Gi`. Because Kubernetes resource quotas are namespace-scoped, this
limit does not include PVCs in other namespaces.

| Budget    | CPU   | Memory |
|-----------|-------|--------|
| small     | 1000m | 1Gi    |
| medium    | 2000m | 2Gi    |
| large     | 4000m | 4Gi    |
| x-large   | 8000m | 8Gi    |
| xx-large  | 8000m | 12Gi   |
| xxx-large | 8000m | 16Gi   |

### Identity and Keycloak Resources
Users listed under `spec.users` must already exist in the configured Keycloak realm.
For each Datalab, the composition provisions these **Keycloak resources**:

- **Groups** for the Datalab and Datalab administrators. The regular group is named after the Datalab, and the administrator group uses `<datalab>-admin`.
- **Group memberships** for the listed users. Users listed in `spec.users` join the regular group; selected administrators also join the admin group.
- A dedicated confidential **OAuth2 client** named after the Datalab. It provides the Datalab's machine identity and role namespace, supports client credentials, and can also protect services intentionally owned by that Datalab. Implicit, device, and direct access grants are disabled.
- A runtime **Secret** named `<datalab>-oauth2-client`, with data keys `client_id` and `client_secret`, generated by Provider Datalab in the runtime workshop namespace for client-credentials automation and direct per-Datalab service protection.
- User, admin, and machine/API **roles**: `ws_access`, `ws_admin`, and `ws_api`.
- Role scope mappings for the generated client because `fullScopeAllowed` is disabled. Tokens only get the generated Datalab client roles that are explicitly mapped.
- Optional access-token audience mappers. Provider Datalab adds one mapper for each value in `EnvironmentConfig.data.iam.extraAudiences`; when the field is omitted or empty, no extra audience mapper is created. Other OAuth clients must emit the same audience when a service requires it.
- Group role bindings for `ws_access` and `ws_admin`, plus a service-account role binding for `ws_api`.

The generated runtime OAuth2 client Secret is still a workspace machine credential and should be readable only by users or automation that may mint client-credentials tokens for that Datalab. Services should treat those client-credentials tokens as machine tokens and require the configured audience when one is used; authorization should require the `ws_api` client role, not user group membership.

Use the runtime `<datalab>-oauth2-client` Secret for machine credentials and services owned by that Datalab. Shared browser ingress can use a separate central platform OAuth client.

---

## Example: Joe (no session by default)

```yaml
# Joe gets a personal datalab s-joe with no pre-created session.
# He must declare and start a session; none runs by default.
# No vCluster is provisioned and no workshop files are attached.
# Credentials to storage are expected to exist in a secret "s-joe" in the same namespace.
# A Keycloak group, role, and client are created; user "joe" must exist in the configured Keycloak realm.
apiVersion: pkg.internal/v1beta2
kind: Datalab
metadata:
  name: s-joe
spec:
  users:
  - joe
  secretName: s-joe
```

- Joe's Datalab has no session runtime until he starts one. The shared
  `package-r` service still runs when Data is enabled.
- Useful for lightweight, on-demand environments.

---

## Example: Jeff, Jim, and Jane (shared store validation, no Kubernetes API access)

```yaml
# Jeff (owner), Jim (admin) and Jane (user) share a datalab s-jeff with no pre-created session.
# This is the canonical shared store-validation example: the lab stays sessionless by default.
# The lab does not use a vCluster and has no workshop files.
# Credentials to storage are expected to exist in a secret "s-jeff" in the same namespace.
# A Keycloak group, role, and client are created; users "jeff", "jim" and "jane" must exist in the configured Keycloak realm.
# This configuration keeps the default baseline security policy:
# - Docker registry is disabled for this shared example.
# - Session quota: increased to 6 Gi memory, 1 Gi storage, budget class "x-large".
# - Kubernetes API access is disabled (kubernetesAccess=false).
# The shared package-r service and all per-session Data tabs are disabled.
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

---

## Example: Jane (vCluster with admin role and higher quota)

```yaml
# Jane runs a datalab s-jane with a default session automatically created.
# That session will run permanently until stopped by the operator,
# and a dedicated vCluster is provisioned for Kubernetes API isolation.
# No workshop files are attached. Credentials to storage are expected
# to exist in a secret "s-jane" in the same namespace.
# A Keycloak group, role, and client are created; user "jane" must exist in the configured Keycloak realm.
# This configuration explicitly overrides default resource quotas and security settings:
# - Security policy: "privileged" → automatically enables Docker with 20 Gi workspace storage.
# - Docker registry is enabled with 3 Gi storage.
# - Session quota: increased to 4 Gi memory, 40 Gi storage, budget class "x-large".
# - Overall environment PVC storage quota: increased to 200 Gi.
# - Kubernetes role: elevated to "admin" for full namespace permissions.
# The Data service disallows create, rename, modify, and delete operations.
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
  overallQuota:
    storage: 200Gi
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

- Jane's session has a **separate virtual Kubernetes control plane** (`vcluster: true`).
- The lab also runs in **privileged** mode, which enables Docker with 20 Gi of session-local workspace storage.
- The Datalab environment namespace accepts at most 200 Gi of aggregate PVC requests.
- The **admin role** grants full control within her namespace or vCluster.
- The Data service is read-only.
- This is the registry-enabled example, so session-backed registry behavior can be validated here.
- Suitable for trusted advanced development or testing that really needs full Kubernetes control.
- Treat this as an operator-approved exception because it combines privileged runtime, registry writes, and elevated Kubernetes authority.

---

## Example: John (with Git-based workshop files)

```yaml
# John has a datalab s-john with a default session automatically created.
# That session will run permanently until stopped by the operator.
# No vCluster is provisioned. Workshop and data files are pulled from Git,
# enabling the workshop tab in the Educates UI.
# The analysis session is declared but stopped, so it keeps its workspace PVC
# without creating a runtime.
# Credentials to storage are expected in a secret "s-john" in the same namespace.
# A Keycloak group, role, and client are created; user "john" must exist in the configured Keycloak realm.
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

Databases run on a dedicated PostgreSQL host managed by Crunchy PostgreSQL Operator. The composition creates `PostgresCluster` resources. To connect from outside the cluster, configure a Gateway API `TLSRoute` and a compatible gateway controller. See the [installation prerequisites](installation.md#prerequisites) for the required operators and APIs.

All additional users are created as regular database roles with limited privileges. Full administrative access is provided through the built-in `postgres` superuser account. This account can create extensions, manage schemas, and grant permissions to other users as needed.

Database credentials are managed by the PostgreSQL operator and stored as Kubernetes Secrets. To locate the credentials for database users, look for Secrets matching:
`*-pguser-*`. These Secrets contain the connection details required to authenticate against the corresponding PostgreSQL roles.
