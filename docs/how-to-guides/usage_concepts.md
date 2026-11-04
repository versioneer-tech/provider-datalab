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

The state defaults to `started`. A started session has a workspace Pod.
A stopped session keeps its PVC without a running workspace. Change its state
to `started` to use the same PVC again.
Several sessions can run at once; each has its own Pod and PVC and shares the
Datalab's credentials and managed services.

With no declared sessions, the Datalab still creates its shared services.
It creates no session Pods or workspace PVCs.

## Persistence

Each declared session has a PVC mounted at `/home/eduk8s`. Its size and
StorageClass come from the selected
[EnvironmentConfig](installation.md#runtime-and-service-defaults).
Use this volume for code, libraries, and workspace files. Keep datasets in
object storage and database records in a managed database. Arrange backup
and recovery with the operator.

## Managed service types

Each service field accepts one type. The API sets that type when you omit it.
The API name for MongoDB is `mongo`.

| Field | Default type |
| --- | --- |
| `spec.databases` | `postgres` |
| `spec.documentStores` | `mongo` |
| `spec.cacheStores` | `redis` |

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

## Document and cache stores

Use these fields to request MongoDB and Redis stores:

```yaml
spec:
  documentStores:
    prod:
      storage: 1Gi
      backupStorage: 3Gi
  cacheStores:
    prod:
      storage: 1Gi
      backupStorage: 3Gi
```

Each store needs its operator installed in the cluster. For the name `prod`,
sessions receive `MONGO_PROD_URI` and `REDIS_PROD_URL`,
along with separate host and credential fields where available.

The composition creates `<store>-mongodb-auth` and `<store>-redis-auth`
Secrets. It watches their values and copies connection
settings into `<datalab>-datalab`. Sessions import those settings as environment
variables. Restart a session to load changed values.

## Backups

Set `backupStorage` to a positive Kubernetes storage quantity, such as `10Gi`,
to create a separate backup PVC. Zero or an omitted value disables backups
without stopping the store.

| Store | Backup schedule | Retention |
| --- | --- | --- |
| PostgreSQL | pgBackRest: full on Sunday, differential on other days, at 01:00 in the operator's time zone. | Four full backups and their dependent backups; the volume also holds WAL. |
| MongoDB | Full `mongodump --oplog --gzip` archive daily at 01:00 UTC. | Four completed archives. |
| Redis | Full `redis-cli --rdb` snapshot daily at 01:00 UTC, checked with `redis-check-rdb`. | Four completed snapshots. |

Size the volume for retained backups and the next full export. Monitor failed
Jobs and free space. Failed MongoDB or Redis jobs preserve completed backups.
Enabling or disabling Redis backups restarts its Pod.

## Data and sharing

The Data service, packageR, is a file browser for the Datalab's object storage.
A session's Data tab opens this shared service. With a permanent Data address,
you can also use it without a running session.

The file browser requires sign-in. Share individual files through temporary
download URLs, or folders through public share links. Recipients do not need
a Datalab account.

The operator controls service availability and read-only permissions through
[EnvironmentConfig](installation.md#runtime-and-service-defaults). Storage
IAM limits every request. For read-only access with AWS tools, see
[S3 client access](s3-access.md).

### Sharing data with the world

Put files in `<datalab>/public` in the bucket named after your Datalab, then
send the public share link. For example, `s-jane/public/results.csv` belongs
to the default public share for `s-jane`. A folder named `public` elsewhere
is not shared automatically.

Public sharing needs a permanent Data address. Upload files through the Data
browser when write access is allowed, or use your storage tools. Anyone with
the link can browse and download those files without signing in.

## Files and the Workshop tab

The operator sets `EnvironmentConfig.data.defaults.files` to load workshop
content from Git, an OCI image, or an HTTP archive. For example:

```yaml
data:
  defaults:
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

## Storage Secret

The input object-storage Secret has the same name as the Datalab. The operator
supplies the Secret and configures its namespace and endpoint during [installation](installation.md#5-supply-storage-credentials).

## Environment settings

The selected EnvironmentConfig controls quotas, persistence, security,
vCluster, registry, Data, and workshop content. See
[values and defaults](installation.md#environmentconfig-values-and-defaults)
for all settings, [Session access](../security/workspace-sessions.md) for
Kubernetes permissions, and [Network policies](../security/sandbox-controls.md)
for allowed traffic.

## Examples

The named users must exist in Keycloak and their storage Secrets must exist
before you apply these manifests in your claim namespace.

| Manifest | Environment | Use |
| --- | --- | --- |
| [Joe](https://github.com/versioneer-tech/provider-datalab/blob/main/examples/base/001-lab.yaml) | `datalab` | Data without a session. |
| [Jeff, Jim, and Jane](https://github.com/versioneer-tech/provider-datalab/blob/main/examples/base/002-lab.yaml) | `datalab` | Shared PostgreSQL, MongoDB, and Redis stores; Jim has the Datalab admin role. |
| [Jane](https://github.com/versioneer-tech/provider-datalab/blob/main/examples/base/003-lab.yaml) | `datalab-custom` | A started session and PostgreSQL. |
| [John](https://github.com/versioneer-tech/provider-datalab/blob/main/examples/base/004-lab.yaml) | `datalab-custom` | Started and stopped sessions with workshop files. |

The [environment examples](https://github.com/versioneer-tech/provider-datalab/blob/main/tests/environmentconfig.yaml)
show the two configurations. `datalab-custom` demonstrates read-only Data,
custom quotas and StorageClasses, privileged security with the Kubernetes
admin role, vCluster, registry, file bundles, Gateway and S3 access, and
internal network rules. Adapt these settings to your platform's access policy.

## Check provisioning

Check the Datalab conditions after applying a resource:

```bash
kubectl get datalabs -n workspace
kubectl describe datalab s-jeff -n workspace
```

`Synced=True` means the composition reconciled. `Ready=True` means its
resources report ready. Read the conditions and events if either is false.
Session state, phase, messages, and URLs remain in `status.sessions`.
Virtual cluster access profiles are reported in `status.connections`. See
[API access](vcluster.md#api-access) for endpoints and Secret references.

### Connect to databases

Use the connection variables supplied to the session, such as
`POSTGRES_PG0_DEV_URL`. The PostgreSQL operator also creates user Secrets named
`*-pguser-*`. Use the database role assigned to your task; the `postgres` role
has administrative access.

See [Additional services](additional_services.md) for a psql example.
