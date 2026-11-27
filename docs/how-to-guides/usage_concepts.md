# Use a Datalab

A `Datalab` resource defines the users, persistent volumes, and services for a team.
The operator supplies the shared storage, identity, and network settings.
Complete [installation](installation.md) before applying these examples.

## Create a workspace

Ask the operator for your claim namespace and confirm that the named users
and their storage Secrets exist. Save this as `team-lab.yaml`, with your own
namespace and usernames:

```yaml
apiVersion: versioneer.at/v1
kind: Datalab
metadata:
  name: team-lab
  namespace: workspace
spec:
  users: [joe]
```

Apply it and check readiness:

```bash
kubectl apply -f team-lab.yaml
kubectl get datalab team-lab -n workspace
```

`Ready=True` means the requested resources are ready. If it stays false, use
[Check provisioning](#check-provisioning). Add stores, volumes, or virtual
clusters using the examples below.

## Volumes

Use `spec.volumes` for named PVCs with optional CSI snapshots in the Datalab
host namespace. They remain when a virtual cluster stops or is removed.
Add `volumeBindings` to a virtual cluster to expose a named volume as a PVC in
one virtual namespace. Applications use the virtual API to mount it. See
[Volumes](volumes.md) for bindings, status, restore, and deletion.

Workloads can create their own PVCs through the virtual API. Arrange backups
for those PVCs separately. Managed databases use the backup settings below.

## Service namespace and storage

The provider creates a namespace with the Datalab name. Data, the registry,
managed stores, and virtual cluster control planes run there. Quotas and
network policies come from EnvironmentConfig. A host ResourceQuota bounds the
team's CPU, memory, and storage; one LimitRange supplies missing container
requests and limits. These controls also apply to virtual cluster workloads.
Connection Secrets are published in the Datalab claim namespace. Data and the
registry use a separate storage-only Secret in the service namespace.

## PostgreSQL

Use `spec.stores` with `type: postgres` to request a PostgreSQL instance and its logical databases:

```yaml
spec:
  stores:
    pg0:
      type: postgres
      names:
      - dev
      - prod
      storage: 1Gi
      backups: true
```

This creates the `pg0` cluster with `dev` and `prod` databases. The PostgreSQL
operator manages the database Pods, credentials, and configured backups.
Stopping an application does not stop the database.
The `<datalab>-postgres-pg0` connection Secret supplies `host`, `port`,
`user`, `password`, and `dev_url` or `prod_url`. When the platform enables an
external TLSRoute, it also supplies `dev_url_external` and `prod_url_external`.
External connections require a client that supports direct TLS with SNI.

### Connect from a workload

Use a [Secret binding](connections.md#bind-a-connection) to make the PostgreSQL
connection available in a virtual namespace. See
[credential access](https://github.com/versioneer-tech/provider-datalab/blob/main/SECURITY.md#credential-access)
before giving applications database credentials.

See [Additional services](additional_services.md#postgresql-with-psql) for a
psql example.

## Valkey

Use the same `stores` map for Valkey:

```yaml
spec:
  stores:
    cache:
      type: valkey
      names: [sessions, jobs]
      storage: 1Gi
      backups: true
```

Each outer name identifies one service instance and its status connection.
Use separate entries for independent Valkey instances; adding `names` only
adds prefixes within the same instance.
The service type cannot change for an existing instance.
The `type` field uses the same value as `status.connections[].type`.
`names` defaults to `[default]`. PostgreSQL uses database names.
Valkey uses key prefixes with a final colon: `sessions:` and `jobs:` in this
example. Clients must add the selected prefix to each key. The names share
instance credentials; prefixes do not restrict access.

Valkey runs as one StatefulSet with persistent storage. Its `maxmemory` is
256 MiB within a 512 MiB container limit. The `noeviction` policy rejects new
writes at that limit. This leaves memory for persistence work. The AOF log is
flushed every second. A crash can lose recent writes that have not reached durable storage.
The data PVC is managed separately from the StatefulSet. Increase `storage`
when its StorageClass supports volume expansion. Shrinking a PVC is not supported.
Valkey needs no separate database operator. Read `url` from `<datalab>-valkey-cache`;
its `redis://` scheme works with Redis-compatible clients.
The connection Secrets contain host and credential fields, a JSON `names`
array and, for Valkey, a JSON `prefixes` map.

Clients must reload connection values after credentials change. See
[connections and Secret bindings](connections.md) for discovery and selected
credential delivery into virtual namespaces.

## Backups

Set `backups: true` on a `spec.stores` or `spec.volumes` entry to enable CSI
snapshots. The default is `false`. No backup PVC or backup size is required.
The platform must meet the [snapshot prerequisites](installation.md#volume-snapshots).

| Resource | Capture | Default retention |
| --- | --- | --- |
| PostgreSQL | Native CloudNativePG cold snapshot. The single instance stops reads and writes during capture. | Platform cleanup policy; seven days is the recommended example. |
| Valkey | Pause writes, wait for `BGSAVE`, then snapshot the data PVC. Writes pause for at most 11 minutes, including time to save and capture. | Four completed snapshots per data PVC UID. |
| Named volume | Snapshot the bound PVC. The application must flush or pause writes when needed. | Two completed snapshots per PVC UID. |

The default schedule is daily at 01:00 UTC. EnvironmentConfig sets each
schedule and snapshot class. PostgreSQL uses a native `ScheduledBackup`;
the platform manages retention. Valkey and named volumes use a retention count
and remove older points only after a new capture is ready and passes its
consistency checks. These backups have no continuous WAL
archive or point-in-time recovery. A stalled CSI request can keep PostgreSQL
paused until the storage fault is resolved. Back up Kubernetes metadata and
credentials separately.

Set `backups: false` to remove the schedule and keep completed recovery points.
Platform retention still applies to PostgreSQL backups.
Enabling or disabling Valkey backups restarts its Pod to change the backup ACL.
Namespace deletion can remove snapshots and their stored data. The platform
must monitor failed backups and snapshot readiness, test restores, and arrange an
independent recovery copy.

### Store removal

Removing a store entry removes its managed resources. For Valkey, this also
deletes the data PVC. Removing only a PostgreSQL database name removes its
managed declaration; it does not delete
the SQL database or its tables. Valkey prefixes are client settings, so removing
a prefix does not delete matching keys. Check that applications no longer use
an entry before removing it.

### Restore a managed store

Ask the platform operator to restore into a separate service and check its data
before use. PostgreSQL recovery uses the completed CNPG Backup and its snapshots.
Keep the required Kubernetes metadata and credentials in a separate backup.

For Valkey, select a ready snapshot with label
`datalabs.versioneer.at/valkey-snapshot-verified: "true"`. The Job sets this label
after checking that the server stayed unchanged and writes stayed paused.
An interrupted capture without this label is removed by the next run.
Create a new PVC from that snapshot. Validate `/data/dump.rdb`
with `valkey-check-rdb`. Start an isolated Valkey process with that PVC mounted at
`/data`, `--dir /data`, and `--appendonly no` to load the saved RDB. Valkey normally
prefers AOF files, which can represent a different recovery boundary. On the
restored PVC, remove the old `appendonlydir`, then use `CONFIG SET appendonly yes`
to build a new AOF. Wait for the rewrite to finish and verify a restart with
AOF enabled. Never change the source PVC during recovery. See
[Valkey persistence](https://valkey.io/topics/persistence/).

For named volumes, see [volume recovery](volumes.md#restore-into-a-new-volume).

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
| [Jeff, Jim, and Jane](https://github.com/versioneer-tech/provider-datalab/blob/main/examples/base/002-lab.yaml) | `datalab` | Shared PostgreSQL and Valkey stores; Jim has the Datalab admin role. |
| [Jane](https://github.com/versioneer-tech/provider-datalab/blob/main/examples/base/003-lab.yaml) | `datalab-custom` | A virtual cluster with service Secret bindings, a bound host volume, PostgreSQL, and the shared registry. |
| [John](https://github.com/versioneer-tech/provider-datalab/blob/main/examples/base/004-lab.yaml) | `datalab-custom` | Read-only Data, custom connections, and namespace policy. |

The [environment examples](https://github.com/versioneer-tech/provider-datalab/blob/main/tests/environmentconfig.yaml)
show the two configurations. `datalab-custom` demonstrates read-only Data,
custom quotas and StorageClasses, Pod security, named virtual clusters,
Gateway and S3 access, and
internal network rules. Adapt these settings to your platform's access policy.
Use `spec.environmentName` for a named override. See
[environment setup](installation.md#4-set-the-shared-environment).

## Check provisioning

Check the Datalab conditions after applying a resource:

```bash
kubectl get datalabs -n workspace
kubectl describe datalab team-lab -n workspace
```

`Synced=True` means the composition reconciled. `Ready=True` means its
resources report ready. Read the conditions and events if either is false.
PVC references, phases, and backup counts are in `status.volumes`.
Service connections and public virtual API profiles are in `status.connections`.
Read each connection through its `secretRef`.

For connection fields and readiness, see the
[API reference](../reference-guides/api.md#datalabstatusconnectionsindex).
[OAuth2 discovery](authentication.md#oauth2-discovery) lists the Datalab client
separately in `status.oauth2`.
