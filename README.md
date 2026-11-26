<h1><img src="docs/imgs/logo.png" height="48" alt="Versioneer logo" /> Provider Datalab</h1>

[![Tests](https://github.com/versioneer-tech/provider-datalab/actions/workflows/pr.yaml/badge.svg?branch=main&event=push)](https://github.com/versioneer-tech/provider-datalab/actions/workflows/pr.yaml)
[![Package version](https://img.shields.io/github/v/tag/versioneer-tech/provider-datalab?include_prereleases&sort=semver&label=package)](https://github.com/versioneer-tech/provider-datalab/pkgs/container/provider-datalab)
[![License](https://img.shields.io/github/license/versioneer-tech/provider-datalab)](LICENSE)

Provider Datalab creates team workspaces on Kubernetes. A `Datalab` resource
declares users, virtual clusters, persistent volumes, and data services.
Crossplane creates them with the platform's identity, network, and storage settings.

> [!NOTE]
> The `main` branch uses `versioneer.at/v1`.
> The `legacy` branch maintains the latest `0.12.x` releases, the last series
> with direct Educates support and limited to `pkg.internal/v1beta2`.

## Get started

[Read the documentation](https://provider-datalab.versioneer.at/) or open its
[local index](docs/index.md). Start with the
[installation guide](docs/how-to-guides/installation.md) for platform setup and
[Use a Datalab](docs/how-to-guides/usage_concepts.md) for team workflows.
Complete manifests are in [examples/base](examples/base).

## Managed stores

Declare managed services in `spec.stores`. Each entry provisions one instance;
`names` selects its logical databases or Valkey key prefixes. It defaults to
`[default]`. The entry name and type match `status.connections`.

```yaml
spec:
  users: [joe]
  stores:
    main:
      type: postgres
      storage: 10Gi
      backups: true
      names: [analytics, catalog]
    cache:
      type: valkey
      storage: 1Gi
      backups: true
      names: [sessions, jobs]
```

The example creates one PostgreSQL instance with two databases and one Valkey
instance. Valkey runs as a StatefulSet with AOF persistence; no separate store
operator is needed. Its clients use the `redis://` URL scheme and add `sessions:`
or `jobs:` to their keys. Names share instance credentials. Prefixes are a
client convention and do not restrict access.

PostgreSQL, Valkey, and named volumes use `backups: true` for CSI snapshots.
Backups default to disabled and need no backup-volume size.
See [usage concepts](docs/how-to-guides/usage_concepts.md) and
[connections](docs/how-to-guides/connections.md).

## Cluster prerequisites

Managed PostgreSQL uses [CloudNativePG](https://cloudnative-pg.io/), with
operator `1.30.2` from Helm chart `0.29.2`. Install it in `cnpg-system`, or set
`EnvironmentConfig.data.database.operatorNamespace` to its namespace. The
supplied provider RBAC must permit the `postgresql.cnpg.io` resources.
Use the intended platform kubeconfig and context in the install command.

```bash
helm repo add cnpg https://cloudnative-pg.github.io/charts
helm upgrade --install cnpg cnpg/cloudnative-pg \
  --kubeconfig /path/to/platform.kubeconfig --kube-context platform \
  --namespace cnpg-system --create-namespace --version 0.29.2 \
  --set fullnameOverride=cnpg --wait
```

Use Kubernetes `1.36` for the complete Datalab feature set and the supported
CloudNativePG range. CloudNativePG `1.30` also tests Kubernetes `1.37`, but does
not list it as supported. See its [support table](https://cloudnative-pg.io/docs/1.30/supported_releases/).

Named Datalab volumes, PostgreSQL, and Valkey with `backups: true` require all of these
cluster capabilities:

- The `snapshot.storage.k8s.io/v1` CRDs: `VolumeSnapshot`,
  `VolumeSnapshotContent`, and `VolumeSnapshotClass`.
- A snapshot controller and a CSI driver with snapshot creation, deletion,
  and volume restore support. Install the driver's CSI snapshotter sidecar.
- A `VolumeSnapshotClass` whose driver matches the data StorageClass
  provisioner. Its `deletionPolicy` must be `Delete` so retention can remove
  expired snapshots and their stored data.
- The snapshot permissions described in [Security](SECURITY.md#postgresql-snapshot-access).

For a virtual cluster, the platform must expose these APIs and classes and
permit snapshot and restore operations through the virtual API. The test
runner does not add host access or change the virtual cluster configuration.
For shared-node vCluster, enable `sync.toHost.volumeSnapshots`,
`sync.toHost.volumeSnapshotContents`, and `sync.fromHost.volumeSnapshotClasses`,
with the required syncer RBAC. CRDs and classes alone do not forward snapshot
requests. See [vCluster volume snapshots](https://www.vcluster.com/docs/vcluster/configure/sync/to-host/storage/volume-snapshots).

Set store storage and backup defaults in the EnvironmentConfig:

```yaml
data:
  database:
    storageClassName: standard-rwo
    snapshotClassName: workspace-snapshots
    schedule: '0 1 * * *'
    maxSnapshots: 4
  cacheStore:
    storageClassName: standard-rwo
    snapshotClassName: workspace-snapshots
    schedule: '0 1 * * *'
    maxSnapshots: 4
```

The schedule uses UTC. `maxSnapshots` accepts 1 through 100 completed backups
per PostgreSQL cluster UID or Valkey data PVC UID. Both snapshot classes default
to `data.volumes.snapshotClassName` when their service setting is absent.
PostgreSQL pauses the instance during capture. Valkey pauses writes for at most
11 minutes and saves an RDB file before capture. Restore Valkey from that RDB
file, then enable AOF persistence. See [backups](docs/how-to-guides/usage_concepts.md#backups).

CloudNativePG coordinates cold snapshots. The single database instance is
unavailable for reads and writes during each backup. This configuration has no
separate WAL archive and does not provide point-in-time recovery. Recovery uses
a completed snapshot.
Monitor failed or stalled backups. A stalled CSI snapshot can keep the primary
paused until the storage fault is resolved.
Back up Kubernetes metadata and credentials separately, and verify recovery
with the installed CSI driver. See [backup behavior](docs/how-to-guides/usage_concepts.md#backups).

## Health checks

Kubernetes uses startup probes to allow initialization, readiness probes to
remove unavailable Pods from Service endpoints, and liveness probes to restart
an unresponsive process.

| Component | Readiness | Liveness and startup |
| --- | --- | --- |
| Data (`package-r`) | HTTP `/health` | HTTP `/health` |
| Data OAuth proxy | HTTP `/ready` | HTTP `/ping` |
| S3 gateway | Gateway forwards `/_ready` to its OAuth proxy | Local `/_live` response |
| S3 OAuth proxy | Gateway forwards `/_auth/ready` to loopback port 4180 | Gateway forwards `/_auth/ping` |
| S3 rclone | Authenticated S3 listing through its local listener | Local unsigned HTTP request must return `403 Forbidden` |
| Registry | `/debug/health` on private port 5001, including the storage driver | TCP port 5000 for liveness; `/debug/health` for startup |
| Valkey | Authenticated local `PING` | Authenticated local `PING`; startup allows ten minutes for data replay |
| Virtual cluster | HTTPS `/readyz` | HTTPS `/healthz` for liveness; `/readyz` for startup |
| PostgreSQL | CloudNativePG instance manager `/readyz` | CloudNativePG instance manager `/healthz` and `/startupz` |
| Crossplane core | HTTP `/readyz` on port 8081 | HTTP `/healthz` on port 8081 |
| Crossplane RBAC manager | HTTP `/metrics` on port 8080 | Same local HTTP listener; this manager has no health endpoint |
| Kubernetes provider | HTTP `/readyz` on port 8081 | HTTP `/healthz` on port 8081 |
| Keycloak provider | HTTP `/metrics` on port 8080 | Same local HTTP listener; this provider has no health endpoint |
| Composition functions | TCP on TLS port 9443 | Same listener; native Kubernetes gRPC probes do not support TLS |

Registry liveness checks the local listener, so an object-storage outage makes
the Pod unready without causing repeated restarts. Its health port is absent
from the Service and public routes. The rclone liveness request uses its
loopback listener and stops at local authentication, before object-storage access.

CloudNativePG and vCluster supply probes for their managed components. The
Crossplane Helm post-renderer adds probes to the core and RBAC manager; it needs
Python with PyYAML. The provider runtime configs set probes for providers and functions. Backup,
cleanup, and initialization tasks exit when complete; Jobs use deadlines and
completion status instead of liveness probes.

## Development

Build from `composition/` and `templates/`; `composition.yaml` is generated.
See [Manifest templates](templates/README.md) for setup and build commands.
Run the [required local checks](tests/README.md), then the
[integration suite](tests/integration/README.md) against a test cluster.

## Security

See [Security](SECURITY.md) for access controls, network setup, and backup permissions.

## License

[Apache License 2.0](LICENSE).
