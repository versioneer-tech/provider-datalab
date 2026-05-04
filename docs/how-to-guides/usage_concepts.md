# Provider Datalab – Usage & Concepts

This section explains how to **use** the `provider-datalab` configuration packages once they are installed. It focuses on the **concepts** of Sessions, Files, vclusters, Storage Secrets, Databases and the optional **Keycloak integration** for identity and access.

Read this page as an operator-facing contract. A `Datalab` gives users a smooth workspace, but durable state should stay visible to the platform team: object-storage credentials, persistent volumes, databases, key-value/cache stores, vector stores, registries, identity resources, and network policy. That visibility lets operators own lifecycle, monitoring, and backups.

---

## Concepts

### Sessions
A `Datalab` claim may declare one or more `spec.sessions`.

- If at least one session is listed, a corresponding **WorkshopSession** is automatically created and will run permanently until stopped by the operator.
- If no sessions are given, no session object is pre-created. The shared runtime namespace and non-session resources can still be reconciled and tested without a `WorkshopSession`.

Sessions can also be patched into the spec later if needed.

### Persistence

Each `Datalab` session is equipped with a **persistent volume** for storing files, in addition to the connected object storage.  This ensures that user data and session state are preserved even if the workshop pod is restarted or rescheduled by Kubernetes.  Installing code libraries, handling metadata, or working with Git repositories often generates many small files that may be updated frequently. A storage class providing **NFS-like capabilities** is usually a good fit for these kinds of workloads, **object storage** abstractions are not.

By default, the **persistent volume claim (PVC)** is **tied to the active session** and will be deleted automatically when the workshop session shuts down (for example, through a culling process when using session mode `auto`). In some environments, this does **not necessarily mean that data is lost**. For example, with an **NFS server** or another **shared storage backend**, restarting the session from the same manifests may recreate the PVC with the same name and point it back at the same physical folder.

That NFS-style reuse is useful when it happens, but it is a storage-backend side effect rather than a Datalab persistence guarantee. It only works when the associated `StorageClass` has its `reclaimPolicy` set to `Retain` (not `Delete`) and when the backend maintains a **consistent link between the PVC name and the actual storage path**. If the underlying storage system assigns **randomized volume identifiers** (such as UIDs for folder paths), the data may still remain on the storage backend after the session ends, but Kubernetes will not automatically reattach it to a new PVC.

For workspaces that must reliably survive `WorkshopSession` deletion, set `spec.persistence.ephemeral: false`. Provider Datalab then creates a stable PVC per declared session in the Educates workshop namespace and configures Educates to use that claim as the `/home/eduk8s` workspace volume. The size still comes from `spec.quota.storage`, and `spec.persistence.storageClassName` may select a StorageClass subject to the operator allowlist in `EnvironmentConfig.data.storageClasses.allowed`.

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

This keeps **compute ephemeral** while **database state remains durable**.

If a Kubernetes gateway service is running in the cluster and enabled in the global configuration, the database **can also be exposed externally**. In that case, corresponding environment variables such as the external hostname or external URL are injected into the session as well.

> Note: The Postgres endpoint is exposed through a gateway `TLSRoute,` which requires immediate TLS with SNI (direct TLS). The PostgreSQL server and libpq-based clients (e.g. psql, psycopg) fully support this. However, some non-libpq drivers such as asyncpg do not yet implement this negotiation correctly and may fail during connection setup.

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

These stores should be visible platform resources, not ad-hoc services hidden inside a user terminal. The `Datalab` claim records that they exist. The underlying operators handle persistence, upgrades, monitoring, and backups. Before enabling them in production, check the backup and restore guarantees of your MongoDB, Redis, or Qdrant operator setup.

### Docker Registry

A Datalab can optionally provide an in-session Docker registry:

```yaml
spec:
  registry:
    enabled: true
    storage: 3Gi
```

This is useful when users need to push and pull images inside the lab. Treat it as workspace-scoped registry storage. If registry contents need backup, retention, scanning, or promotion into a central registry, define that in platform policy before enabling it.

### Authentication

Provider Datalab is a workspace building block. It can wire authentication into the runtime, but the cleaner production pattern is often to delegate authentication to the surrounding platform, especially at ingress.

Multiple options are possible:

- Enable built-in runtime authentication. By default, `auth.type = credentials` uses the same credentials that are used to access the connected object-storage buckets for session login. This is a simple basic-auth style option, but it ties workspace users to the credentials known by the Datalab runtime.
- Set `auth.type = none` and let another platform component protect access before requests reach the workspace. This does not mean that unauthenticated access is required; it means authentication is delegated to another layer, such as the Kubernetes ingress controller.

Delegating authentication is often more flexible because users accessing a workspace do not necessarily have to exist in Keycloak. For example, a workspace ingress can be protected by `oauth2-proxy` with NGINX ingress annotations:

```yaml
nginx.ingress.kubernetes.io/auth-url: "https://auth.acme.org/oauth2/auth"
nginx.ingress.kubernetes.io/auth-signin: "https://auth.acme.org/oauth2/start?rd=$escaped_request_uri"
```

Those annotations can be added by platform policy instead of being specified in every Datalab. One option is a Kyverno mutation policy:

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: annotate-datalab-ingresses
spec:
  background: false
  rules:
  - name: add-oauth2-proxy-annotations-for-datalab-domain
    match:
      any:
      - resources:
          kinds:
          - Ingress
    preconditions:
      all:
      - key: "{{ request.object.spec.rules[?ends_with(host, '.datalab.acme.org')] | length(@) }}"
        operator: GreaterThan
        value: 0
    mutate:
      patchStrategicMerge:
        metadata:
          annotations:
            nginx.ingress.kubernetes.io/auth-url: "https://auth.acme.org/oauth2/auth"
            nginx.ingress.kubernetes.io/auth-signin: "https://auth.acme.org/oauth2/start?rd=$escaped_request_uri"
```

Kyverno is only one way to apply this policy. The same result can be achieved with a mutating admission webhook or any other platform automation that consistently annotates the generated Ingress resources.

Keycloak-managed access is supported. When it is used, the composition automatically provisions the Keycloak client, groups, roles, role bindings, and memberships needed for the workspace.

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

- **Groups** for the datalab and datalab administrators
- **Group memberships** for the listed users
- A dedicated **OAuth2 client**
- User and admin **roles**, plus the role bindings for the generated groups

This ensures that authentication and authorization are consistently enforced across the runtime and UI. If authentication is delegated to the ingress or another platform component, the identities allowed through that outer layer are managed by that component and do not necessarily have to be users in the Datalab Keycloak realm.

---

## Example: Joe (no session by default)

```yaml
# Joe gets a personal datalab s-joe with no pre-created session.
# He must explicitly start a session himself; nothing is running by default.
# No vcluster is provisioned and no workshop files are attached.
# Credentials to storage are expected to exist in a secret "s-joe" in the same namespace.
# A Keycloak group, role, and client are created; user "joe" must exist in Keycloak.
apiVersion: pkg.internal/v1beta1
kind: Datalab
metadata:
  name: s-joe
spec:
  users:
  - joe
  secretName: s-joe
```

- Joe’s Datalab exists but is idle until he launches a session.
- Useful for lightweight, on-demand environments.
- Keycloak ensures Joe is authorized to access his workspace.

---

## Example: Jeff, Jim, and Jane (shared store validation, privileged with Docker)

```yaml
# Jeff (owner), Jim (admin) and Jane (user) share a datalab s-jeff with no pre-created session.
# This is the canonical shared store-validation example: the lab stays sessionless by default.
# The lab does not use a vcluster and has no workshop files.
# Credentials to storage are expected to exist in a secret "s-jeff" in the same namespace.
# A Keycloak group, role, and client are created; users "jeff", "jim" and "jane" must exist in Keycloak.
# This configuration runs the lab in privileged mode:
# - Security policy: "privileged" → automatically enables Docker with 20 Gi workspace storage.
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
apiVersion: pkg.internal/v1beta1
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
    policy: privileged
    kubernetesAccess: false
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
- Runs in **privileged mode** with **Docker support** and increased ephemeral disk (20 Gi).
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
apiVersion: pkg.internal/v1beta1
kind: Datalab
metadata:
  name: s-jane
spec:
  users:
    - jane
  secretName: s-jane
  sessions:
    - default
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
- Suitable for advanced development or testing requiring full Kubernetes control.
- Keycloak enforces role-based access protection for this lab.

---

## Example: John (with Git-based workshop files)

```yaml
# John has a datalab s-john with a default session automatically created.
# That session will run permanently until stopped by the operator.
# No vcluster is provisioned. Workshop and data files are pulled from Git,
# enabling the workshop tab in the Educates UI.
# Credentials to storage are expected in a secret "s-john" in the same namespace.
# A Keycloak group, role, and client are created; user "john" must exist in Keycloak.
apiVersion: pkg.internal/v1beta1
kind: Datalab
metadata:
  name: s-john
spec:
  users:
  - john
  secretName: s-john
  sessions:
  - default
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

Starting with version 0.3.0, databases can be provisioned on a dedicated PostgreSQL host. Optionally, these databases can also be exposed externally using a `TLSRoute`, enabling secure access from outside the cluster. External exposure requires a Kubernetes Gateway Controller that operates at Layer-4, such as Envoy.

All additional users are created as regular database roles with limited privileges. Full administrative access is provided through the built-in `postgres` superuser account. This account can create extensions, manage schemas, and grant permissions to other users as needed.

Database credentials are managed by the PostgreSQL operator and stored as Kubernetes Secrets. To locate the credentials for database users, look for Secrets matching:
`*-pguser-*`. These Secrets contain the connection details required to authenticate against the corresponding PostgreSQL roles.

---

## Summary

- A `Datalab` defines users, sessions, optional vcluster, quotas, and security policies.
- A `Datalab` can also define platform-managed databases, document stores, key-value/cache stores, vector stores, and registry storage.
- Security controls combine **Pod Security Standards**, **Kubernetes roles**, and **Docker privilege** toggles.
- Each Datalab requires a storage credential Secret.
- Durable data services remain visible to operators, which is the basis for backup, restore, monitoring, and lifecycle responsibility.
- Object-storage buckets are created outside Provider Datalab, for example with Provider Storage; Provider Datalab consumes the resulting credentials.
- For Keycloak-managed access, users must already exist in Keycloak; the Datalab provisions groups, memberships, a client, roles, and role bindings.
- For delegated access, `auth.type = none` leaves authentication to the ingress layer or another platform component.
- Sessions may be long-lived (auto-created) or on-demand (user started).
- Workshop files enable the Educates UI workshop tab.
- Check `kubectl get datalabs` for readiness and confirm Secret and Keycloak resource creation where applicable.
