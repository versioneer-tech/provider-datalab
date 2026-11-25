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
`names` selects its logical databases or Redis key prefixes. It defaults to
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
      type: redis
      storage: 1Gi
      backups: true
      names: [sessions, jobs]
```

The example creates one PostgreSQL service and one Redis service. Redis clients
must add `sessions:` or `jobs:` to their keys. Names share instance credentials;
prefixes do not restrict access. PostgreSQL, Redis, and named volumes use `backups: true` for CSI snapshots.
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

Named Datalab volumes, PostgreSQL, and Redis with `backups: true` require all of these
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

Set the PostgreSQL storage and backup defaults in the EnvironmentConfig:

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
per PostgreSQL cluster UID or Redis data PVC UID. Both snapshot classes default
to `data.volumes.snapshotClassName` when their service setting is absent.
PostgreSQL pauses the instance during capture. Redis pauses writes for at most
11 minutes and saves an RDB file before capture. Restore Redis from that RDB
file, then enable AOF persistence. See [backups](docs/how-to-guides/usage_concepts.md#backups).

CloudNativePG coordinates cold snapshots. The single database instance is
unavailable for reads and writes during each backup. This configuration has no
separate WAL archive and does not provide point-in-time recovery. Recovery uses
a completed snapshot.
Monitor failed or stalled backups. A stalled CSI snapshot can keep the primary
paused until the storage fault is resolved.
Back up Kubernetes metadata and credentials separately, and verify recovery
with the installed CSI driver. See [backup behavior](docs/how-to-guides/usage_concepts.md#backups).

## Development

Build from `composition/` and `templates/`; `composition.yaml` is generated.
See [Manifest templates](templates/README.md) for setup and build commands.
Run the [required local checks](tests/README.md), then the
[integration suite](tests/integration/README.md) against a test cluster.

## Security

See [Security](SECURITY.md) for access controls, network setup, and backup permissions.

## License

[Apache License 2.0](LICENSE).
