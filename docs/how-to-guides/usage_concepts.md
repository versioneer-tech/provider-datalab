# Use a Datalab

A `Datalab` resource defines the users and services for a team.
The operator supplies the shared storage, identity, and network settings.
Complete [installation](installation.md) before applying these examples.

## Service namespace and storage

The composition creates a namespace with the Datalab name. Data and managed
stores run there. Each named virtual cluster has its own control-plane PVC;
users create workload PVCs through its virtual Kubernetes API.
The environment's `defaults.overallQuota.storage` limits the sum of PVC
requests in the service namespace. Arrange backup and recovery with the operator.

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
The `<datalab>-postgres-pg0` connection Secret supplies `host`, `port`,
`user`, `password`, and `dev_url` or `prod_url`. When the platform enables an
external TLSRoute, it also supplies `dev_url_external` and `prod_url_external`.
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
read `uri` from `<datalab>-mongo-prod` or `url` from `<datalab>-redis-prod`.
The connection Secrets also contain host and credential fields.

The composition watches the operator authentication Secrets and updates each
service connection separately. Clients must reload changed values. See
[connection sets and Secret bindings](connections.md) for discovery and selected
credential delivery into virtual namespaces.

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
The operator can publish a permanent authenticated Data address. Without one,
Data accepts trusted callers inside the service namespace.

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

## Virtual clusters

Declare independent Kubernetes runtimes in `spec.vclusters`. Each instance
has separate routes, storage, and access profiles. See [virtual clusters](vcluster.md).

## Storage Secret

Set `spec.secretName` to the input object-storage Secret name. If omitted,
the Datalab name is used. The operator supplies the Secret and configures its
namespace and endpoint during [installation](installation.md#5-supply-storage-credentials).

## Environment settings

The selected EnvironmentConfig controls storage quotas, security, Data,
virtual cluster defaults, and network access. See
[values and defaults](installation.md#environmentconfig-values-and-defaults),
[workload access](../security/workload-access.md), and
[network policies](../security/sandbox-controls.md).

## Examples

The named users must exist in Keycloak and their storage Secrets must exist
before you apply these manifests in your claim namespace.

| Manifest | Environment | Use |
| --- | --- | --- |
| [Joe](https://github.com/versioneer-tech/provider-datalab/blob/main/examples/base/001-lab.yaml) | `datalab` | Data and storage access. |
| [Jeff, Jim, and Jane](https://github.com/versioneer-tech/provider-datalab/blob/main/examples/base/002-lab.yaml) | `datalab` | Shared PostgreSQL, MongoDB, and Redis stores; Jim has the Datalab admin role. |
| [Jane](https://github.com/versioneer-tech/provider-datalab/blob/main/examples/base/003-lab.yaml) | `datalab-custom` | Named virtual clusters and PostgreSQL. |
| [John](https://github.com/versioneer-tech/provider-datalab/blob/main/examples/base/004-lab.yaml) | `datalab-custom` | Read-only Data with custom environment settings. |

The [environment examples](https://github.com/versioneer-tech/provider-datalab/blob/main/tests/environmentconfig.yaml)
show the two configurations. `datalab-custom` demonstrates read-only Data,
custom quotas and StorageClasses, Pod security, named virtual clusters,
Gateway and S3 access, and
internal network rules. Adapt these settings to your platform's access policy.

## Check provisioning

Check the Datalab conditions after applying a resource:

```bash
kubectl get datalabs -n workspace
kubectl describe datalab s-jeff -n workspace
```

`Synced=True` means the composition reconciled. `Ready=True` means its
resources report ready. Read the conditions and events if either is false.
Service and virtual cluster connection references are reported in `status.connections`. See
[API access](vcluster.md#api-access) for endpoints and Secret references.

### Connect to databases

Read `dev_url` from the generated `<datalab>-postgres-pg0` connection Secret. The PostgreSQL operator also creates user Secrets named
`*-pguser-*`. Use the database role assigned to your task; the `postgres` role
has administrative access.

See [Additional services](additional_services.md) for a psql example.
