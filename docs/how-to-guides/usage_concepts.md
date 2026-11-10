# Use a Datalab

A `Datalab` resource defines the users, sessions, and services for a team.
The operator supplies the shared storage, identity, and network settings.
Complete [installation](installation.md) before applying these examples.

## Sessions

A session provides a named workspace PVC in a virtual cluster. Declare its
cluster, namespace, and storage size in `spec.sessions`:

```yaml
spec:
  vclusters:
    vc0: {}
  sessions:
  - name: analysis
    vcluster: vc0
    namespace: demo
    pvcSize: 2Gi
```

The provider creates `demo/session-analysis` in `vc0`. Start a Sandbox that
mounts this PVC to use the workspace. See [Run a sandbox](sandboxes.md) for
local connection scripts, file operations, commands, and workload replacement.
Declaring a session does not start a workload. Several sessions can share the
Datalab's managed services while using separate PVCs.

`status.sessions` reports the virtual cluster and PVC location:

```yaml
status:
  sessions:
  - name: analysis
    vcluster: vc0
    namespace: demo
    pvcName: session-analysis
```

## Persistence

A Sandbox can mount its session PVC at `/workspace`. Removing the Sandbox
keeps that PVC and its files. Stop workloads before removing a session entry
from the Datalab; entry removal deletes the PVC. Keep datasets in object
storage and database records in a managed database. Arrange backup and
recovery with the operator.

## Service namespace and storage

The provider creates a namespace with the Datalab name. Data, the registry,
managed stores, and virtual cluster control planes run there. Quotas and
network policies come from EnvironmentConfig. A host ResourceQuota bounds the
team's CPU, memory, and storage; one LimitRange supplies missing container
requests and limits. These controls also apply to virtual cluster workloads.
Connection Secrets are published in the Datalab claim namespace. Data and the
registry use a separate storage-only Secret in the service namespace.

## PostgreSQL

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
Stopping a Sandbox does not stop the database.
The `<datalab>-postgres-pg0` connection Secret supplies `host`, `port`,
`user`, `password`, and `dev_url` or `prod_url`. When the platform enables an
external TLSRoute, it also supplies `dev_url_external` and `prod_url_external`.
External connections require a client that supports direct TLS with SNI.

### Connect from a workload

Use a [Secret binding](connections.md#bind-a-connection) to make the PostgreSQL
connection available in a virtual namespace. The generated connection uses
the `postgres` account, which has administrative access. Create a separate
database login and grants for applications that need less access.

See [Additional services](additional_services.md#postgresql-with-psql) for a
psql example.

## MongoDB and Redis

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
[connections and Secret bindings](connections.md) for discovery and selected
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

## OCI registry

The shared registry is available at `https://s-jane.lab.acme.com/v2/` for
Datalab `s-jane`. Use the `registry` connection named `primary` in
`status.connections` to find its Secret. Enter that Secret's `user` and
`password` at the Docker login prompt:

```bash
docker login s-jane.lab.acme.com
docker tag example:latest s-jane.lab.acme.com/team/example:latest
docker push s-jane.lab.acme.com/team/example:latest
```

Docker login and image references use the hostname without `/v2/`.
Images use the Datalab's S3 bucket and remain in storage when the registry is disabled.
The operator can disable the registry through the EnvironmentConfig.

## Examples

The named users must exist in Keycloak and their storage Secrets must exist
before you apply these manifests in your claim namespace.

| Manifest | Environment | Use |
| --- | --- | --- |
| [Joe](https://github.com/versioneer-tech/provider-datalab/blob/main/examples/base/001-lab.yaml) | `datalab` | Data and storage access. |
| [Jeff, Jim, and Jane](https://github.com/versioneer-tech/provider-datalab/blob/main/examples/base/002-lab.yaml) | `datalab` | Shared PostgreSQL, MongoDB, and Redis stores; Jim has the Datalab admin role. |
| [Jane](https://github.com/versioneer-tech/provider-datalab/blob/main/examples/base/003-lab.yaml) | `datalab-custom` | A virtual cluster with service Secret bindings, PostgreSQL, and the shared registry. |
| [John](https://github.com/versioneer-tech/provider-datalab/blob/main/examples/base/004-lab.yaml) | `datalab-custom` | Read-only Data, custom connections, and namespace policy. |

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
Session PVC names and locations are in `status.sessions`.
Service connections and public virtual API profiles are in `status.connections`.
Read each connection through its `secretRef`.

For connection fields and readiness, see the
[API reference](../reference-guides/api.md#datalabstatusconnectionsindex).
[OAuth2 discovery](authentication.md#oauth2-discovery) lists the Datalab client
separately in `status.oauth2`.
