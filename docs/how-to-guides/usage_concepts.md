# Use a Datalab

A `Datalab` resource defines the users, sessions, and services for a team.
The operator supplies the shared storage, identity, and network settings.
Complete [installation](installation.md) before applying these examples.

## Sessions

A session is a named workspace with an editor, terminal, and persistent home
directory. Declare the sessions you need in `spec.sessions`:

```yaml
spec:
  sessions:
  - name: default
  - name: analysis
    state: stopped
```

The state defaults to `started`. A started session has an Educates
`WorkshopSession` and a workspace Pod. A stopped session keeps its PVC without
a running workspace. Change its state to `started` to use the same PVC again.
Several sessions can run at once; each has its own Pod and PVC and shares the
Datalab's credentials and managed services.

With no declared sessions, the Datalab still creates its shared services.
It creates no session Pods or workspace PVCs.

## Persistence

Each declared session has a PVC mounted at `/home/eduk8s`. Set its size and
StorageClass with:

```yaml
spec:
  quota:
    storage: 20Gi
  persistence:
    storageClassName: sbs-default
```

The operator can restrict classes through
`EnvironmentConfig.data.storageClasses.allowed`. A requested class must be in
that list; otherwise the first listed class is used. With no list, Kubernetes
uses the requested class or the cluster default.

Use the session volume for code, libraries, and workspace files. Keep datasets
in object storage and database records in a managed database. Arrange backups
and recovery with the operator. Test session stop, start, and recovery with
your platform's storage before relying on them.

## Database

Use `spec.databases` to request a PostgreSQL cluster and its logical databases:

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

This creates the `pg0` cluster with `dev` and `prod` databases. The PostgreSQL
operator manages the database Pods, credentials, and configured backups.
Stopping a session does not stop the database.

Sessions receive connection settings such as `POSTGRES_PG0_HOST`,
`POSTGRES_PG0_PORT`, and `POSTGRES_PG0_DEV_URL`. The generated
`<datalab>-datalab` Secret holds these values. When the platform enables an
external TLSRoute, it also supplies `POSTGRES_PG0_DEV_URL_EXTERNAL`.
External connections require a client that supports direct TLS with SNI.

## Document, cache, and vector stores

Use these fields to request MongoDB, Redis, and Qdrant stores:

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

Each store needs its operator installed in the cluster. For the name `prod`,
sessions receive `MONGO_PROD_URI`, `REDIS_PROD_URL`, and `QDRANT_PROD_URL`,
along with separate host and credential fields where available.

The composition creates `<store>-mongodb-auth`, `<store>-redis-auth`, and
`<store>-qdrant-auth` Secrets. It watches their values and copies connection
settings into `<datalab>-datalab`. Sessions import those settings as environment
variables. Restart a session to load changed values.

## Docker registry

Use `spec.registry` to add a registry to the session:

```yaml
spec:
  registry:
    enabled: true
    storage: 3Gi
```

Use it to push and pull images within the Datalab. Agree with the operator on
retention, scanning, and backups if you need to keep the images.

## Data and sharing

The Data service, packageR, is a file browser for the Datalab's object storage.
It is enabled by default. A session's Data tab opens this shared service.
When the operator enables a permanent Data address, you can use it without a
running session.

The file browser requires sign-in. You can share individual files through
temporary download URLs, or folders through public share links. Recipients
do not need a Datalab account.

Set `spec.data.enabled: false` when creating a Datalab to omit the service and
its Data tabs. This setting cannot change after creation.
Set `spec.data.readOnlyMount: true` for read-only application permissions.
Storage IAM still limits every request.

### Sharing data with the world

Put files in `<datalab>/public` in the bucket named after your Datalab, then
send the public share link. For example, `s-jane/public/results.csv` belongs
to the default public share for `s-jane`. A folder named `public` elsewhere
is not shared automatically.

Public sharing needs a permanent Data address. Upload files through the Data
browser when write access is allowed, or use your storage tools. Anyone with
the link can browse and download those files without signing in.

## Authentication

The operator protects session ingress and checks access against the generated
Datalab roles. Users in `spec.users` must exist in the configured Keycloak realm.
See [Authentication](authentication.md) for the client and role model and the
NGINX and APISIX setup examples.

## Files and the Workshop tab

Use `spec.files` to load workshop content from Git, an OCI image, or an HTTP
archive. For example:

```yaml
spec:
  files:
  - git:
      url: https://github.com/versioneer-tech/datalab-example
      ref: origin/main
    includePaths:
    - /workshop/**
    path: .
```

Adding a source enables the Workshop tab. With no sources, the tab is hidden.
Use `includePaths`, `excludePaths`, `newRootPath`, and `path` to select and
place the files.

## vCluster

Set `spec.vcluster: true` to give each started session a virtual Kubernetes
API. With `false`, workloads use the host cluster namespace directly.
The virtual API does not isolate Pods from the host. The host's network and
Pod security rules still apply.

## Storage Secret

A Datalab needs credentials for an existing S3-compatible store. Set
`spec.secretName` to the input Secret name. If omitted, the Datalab name is used.
The operator sets its namespace with
`EnvironmentConfig.data.storage.secretNamespace` and the endpoint with
`EnvironmentConfig.data.storage.endpoint`.

The Secret must contain `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`.
The Data service needs network access to that endpoint. Browsers connect to
Data rather than directly to storage.

## Security and access policy

Use `spec.security` to set session privileges and access:

| Field | Effect |
| --- | --- |
| `policy` | Selects `restricted`, `baseline`, or `privileged` Pod security. Privileged mode enables Docker with local storage. |
| `kubernetesAccess` | Controls whether the session gets a Kubernetes service account token. |
| `kubernetesRole` | Selects `view`, `edit`, or `admin` access. |
| `externalEgress` | Controls external network access through the generated policies. |

The operator sets shared defaults in `EnvironmentConfig.data.defaults.security`.
Data uses the same egress rules to reach object storage. See
[Network policies](../security/sandbox-controls.md) for the policy rules and
[Session access](../security/workspace-sessions.md) for what a session can use.

## Resource quotas

Use `spec.quota` for session limits and `spec.overallQuota` for the total PVC
requests in the Datalab environment namespace:

```yaml
spec:
  quota:
    memory: 4Gi
    storage: 20Gi
    budget: large
  overallQuota:
    storage: 100Gi
```

Session defaults are `2Gi` memory, `1Gi` storage, and the `medium` Educates
budget. The operator can change them through
`EnvironmentConfig.data.defaults.quota`.

The total storage quota defaults to `100Gi`, or
`EnvironmentConfig.data.defaults.overallQuota.storage` when set. It covers PVC
requests in the environment namespace, not PVCs in other namespaces.

## S3 client access

The optional S3 endpoint lets AWS tools read Datalab data through the same host
as the Data browser. It is experimental and read only. The operator enables
it for the environment. See [S3 client access](s3-access.md) for setup, token
handling, and AWS CLI examples.

## Identity and Keycloak resources

Provider Datalab creates the client, groups, roles, and memberships for each
Datalab. Human users get `ws_access` or `ws_admin`; the client service account
gets `ws_api`. See [Keycloak clients and roles](authentication.md#keycloak-clients-and-roles)
for how services use them.

## Examples

These examples use the manifests in `examples/base/`. The named users must
exist in Keycloak and their input storage Secrets must exist before you apply
the resources. Apply them in your claim namespace.

### Joe: Data without a session

Joe uses the shared Data service without starting a workspace. He can add a
named session later.

```yaml
apiVersion: pkg.internal/v1beta2
kind: Datalab
metadata:
  name: s-joe
  annotations:
    datalabs.pkg.internal/environment: datalab-custom
spec:
  users:
  - joe
  secretName: s-joe
```

### Jeff, Jim, and Jane: shared stores

This Datalab requests PostgreSQL, MongoDB, Redis, and Qdrant stores. It starts
no session and disables Data, Kubernetes API access, and external egress.

```yaml
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

### Jane: a privileged workspace

Jane starts a session with a virtual Kubernetes API, the admin role, a
registry, and a PostgreSQL database. Data is read only. Use this setup only
when the operator has approved privileged workloads.

```yaml
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

### John: workshop files from Git

John starts a default session and keeps an analysis session stopped. Workshop
files come from Git, which enables the Workshop tab.

```yaml
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
  persistence:
    storageClassName: sbs-default-retain
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

## Verifying provisioning

Check the Datalab conditions after applying a resource:

```bash
kubectl get datalabs -n workspace
kubectl describe datalab s-jeff -n workspace
```

`Synced=True` means the composition reconciled. `Ready=True` means its
resources report ready. Read the conditions and events if either is false.

### Find the storage Secret

Check that the referenced Secret exists in `storage.secretNamespace`:

```bash
kubectl get secret s-jeff -n workspace
```

Use your platform's credential tools to inspect or rotate its values.

### Connect to databases

Use the connection variables supplied to the session, such as
`POSTGRES_PG0_DEV_URL`. The PostgreSQL operator also creates user Secrets named
`*-pguser-*`. Use the database role assigned to your task; the `postgres` role
has administrative access.

See [Additional services](additional_services.md) for a psql example.
