# Integration tests

Run the [unit suite](../README.md#unit-suite) first. Then use the dedicated
`provider-datalab-it` Kind cluster or an existing test cluster. Every Kubernetes
and Helm call uses an explicit kubeconfig and context.

Setup installs Crossplane and dependencies, applies the current XRD and
Composition, and waits for the Datalab schema. Disposable MinIO supplies object
storage. See the [Helm values](../../deploy/crossplane-values.yaml) and
[dependency versions](../../docs/how-to-guides/installation.md#dependency-baseline).

## Select a cluster

Kind setup installs NetworkPolicy enforcement, a snapshot-capable CSI driver,
its snapshotter sidecar, a snapshot controller, and the three snapshot CRDs.
The shared Kind config selects Kubernetes 1.37.0 for stable admission policies.
These capabilities are required in Kind, both locally and in GitHub Actions.
An unsuccessful Kind capability check fails the run.

On existing targets, capability probes determine which checks can run. Missing
capabilities produce a `SKIPPED` result with a reason. Other checks continue.

Snapshot checks require a matching StorageClass and VolumeSnapshotClass with
`Delete` policy, the snapshot APIs, and snapshot management permissions. The
probe checks access for the test identity, Crossplane, and the Kubernetes
provider. Supply `--snapshot-class` to enable it. Without that option, snapshot
tests are skipped on existing targets.
After setup, volume tests check the generated backup ServiceAccount's access.
Other PVCs, Secrets, snapshot contents, class changes, and snapshots in another
namespace must be denied. A failure after a successful probe fails the test.

For an existing cluster, supply its kubeconfig, context, StorageClass, Service
CIDR, and comma-separated Pod CIDRs. Use values from the selected cluster:

```bash
tests/integration/run.bash all \
  --kubeconfig /tmp/datalab-test.kubeconfig --context datalab-test \
  --storage-class standard-rwo \
  --snapshot-class workspace-snapshots \
  --service-cidr 10.20.0.0/16 --pod-cidrs 10.30.0.0/16 \
  --image-registry registry.acme.com/team/integration
```

Add `--check` to check access and settings without installing resources. An
existing cluster needs permission for CRDs, admission policies, and service
account impersonation. The suite installs Crossplane and database operators.
Existing prerequisite namespaces must have the label
`datalabs.versioneer.at/integration=true`; otherwise setup stops before it
changes them. Use namespaces and cluster-wide resources reserved for tests.

The NetworkPolicy probe checks a connection before a deny policy, checks that
the policy blocks it, then checks that traffic returns after policy removal.
It uses a temporary namespace and removes it after the probe. Traffic checks
run only when this probe succeeds. Resource-default and quota checks always run.
A vCluster without policy enforcement skips traffic checks.

The registry must accept pushes and be reachable from cluster nodes. The
runner uses an empty Docker config unless you supply `--docker-config <directory>`
with a config prepared for the test. To use published images,
omit `--image-registry` and set `S3_CLIENT_IMAGE`, `VCLUSTER_CLIENT_IMAGE`, and
`VCLUSTER_CATALOG_IMAGE`. Build them from the matching Dockerfiles in this
checkout. For private images, create a pull Secret in `workspace` and pass its
name with `--image-pull-secret`. The suite copies it to the S3 client namespace
and binds it into the nested catalog namespace.

Standalone profile scripts use `PROVIDER_DATALAB_CLUSTER=existing`,
`PROVIDER_DATALAB_KUBECONFIG`, and `PROVIDER_DATALAB_CONTEXT` for the target.
Set `PROVIDER_DATALAB_STORAGE_CLASS`, `PROVIDER_DATALAB_SERVICE_CIDR`, and
`PROVIDER_DATALAB_POD_CIDRS` to the same values used by the runner. Set
`PROVIDER_DATALAB_IMAGE_REGISTRY` when the profile builds remote images.
Set `PROVIDER_DATALAB_SNAPSHOT_CLASS` for snapshot checks on existing targets.
Kind uses its setup defaults. A virtual target must expose the snapshot APIs
and matching classes through its platform configuration. The runner uses only
the selected API and does not change host RBAC or vCluster sync settings.
The virtual cluster profile needs stable mutating admission policies on its
selected target (Kubernetes 1.36 or later).
Use `PROVIDER_DATALAB_CONTROL_PLANE_STORAGE_CLASS` when control-plane PVCs need
a different class from workload and snapshot-test PVCs.

## Run profiles

Run all profiles with one platform setup, or select one profile:

```bash
tests/integration/run.bash all --kind
tests/integration/run.bash verify-s3
```

Kind is the default. Its context is `kind-provider-datalab-it`; the kubeconfig
is `/tmp/provider-datalab-it.kubeconfig`. The
[`cluster setup`](create-cluster.bash) prepares NetworkPolicy enforcement,
NFS CSI storage, and snapshots on new and reused clusters. It installs the
[Kubernetes network policy controller](https://kube-network-policies.sigs.k8s.io/docs/quick-start/)
without replacing Kind's network plugin. The default classes are `datalab-nfs` and
`datalab-nfs-snapshots`. Use `--storage-class` and `--snapshot-class` to select
other matching classes.

Kind control-plane PVCs use the local `standard` class for SQLite.
Workload PVCs and named volumes use `datalab-nfs` for CSI snapshot checks.
The generated allowlist includes both classes; `datalab-nfs` remains the default.

[`kind-storage.bash`](kind-storage.bash) installs NFS CSI `4.13.6`, snapshot
CRDs and controllers, and an NFS-Ganesha server in `test-volume-snapshots`.
Kind nodes need NFS client support. The server uses `emptyDir`; replacing its
Pod discards the test data. This setup is for the dedicated test cluster.

The runner reuses matching dependency releases after readiness checks.
To apply charts again after changing values, set
`REUSE_DEPENDENCIES=0`:

```bash
REUSE_DEPENDENCIES=0 tests/integration/run.bash verify-s3
```

Successful profiles remove their test resources. Failed profiles keep them for
diagnosis. To keep successful resources, set the matching variable to `1`:

| Profile | Variable |
| --- | --- |
| Network | `KEEP_NETWORK_RESOURCES` |
| Data | `KEEP_DATA_RESOURCES` |
| S3 | `KEEP_S3_RESOURCES` |
| Registry | `KEEP_REGISTRY_RESOURCES` |
| PostgreSQL | `KEEP_POSTGRES_RESOURCES` |
| MongoDB or Redis | `KEEP_STORE_RESOURCES` |
| Volumes | `KEEP_VOLUME_RESOURCES` |
| Virtual clusters | `KEEP_VCLUSTER_RESOURCES` |

## Datalab manifests by profile

| Profile | Fixture | Checks |
| --- | --- | --- |
| `verify-network` | [Two Datalabs](manifests/network/datalabs.yaml) | Resource defaults and quota rejection. Kind also checks namespace isolation, external egress, and MinIO access. |
| `verify-registry` | [Registry](manifests/registry/datalab.yaml) | Authenticate with the published Secret, then write and read a blob in S3-backed storage. |
| `verify-data` | [Data](manifests/data/datalabs.yaml) | File write/read, credential rotation with restart, and read-only write rejection. |
| `verify-s3` | [S3](manifests/s3/datalab.yaml) | TLS, list/HEAD/GET/range reads, write/delete rejection, and browser access after S3 is disabled. |
| `verify-postgres` | [PostgreSQL](manifests/postgres/datalab.yaml) | SQL write/read through connection Secrets; backup configuration enabled on `pg0` and absent on `pg1`. |
| `verify-mongo` | [MongoDB](manifests/mongo/datalab.yaml) | Document write/read; back up and restore the probe document with oplog replay in a separate MongoDB process. |
| `verify-redis` | [Redis](manifests/redis/datalab.yaml) | Key write/read; restore a backup in a separate Redis process, then disable backups and retain the backup PVC. |
| `verify-volumes` | [Volumes](manifests/volumes/datalab.yaml) | Host PVCs, snapshot Jobs, restore contents, retention, backup status, and storage removal without a virtual cluster. |
| `verify-vcluster` | [Virtual clusters](manifests/vcluster/datalab.yaml) | Access, routing, workload and STAC behavior, and application PVC persistence. See below. |

Fixtures use profile-named Secrets and enable the services they test. Network
and Data restore shared environment settings; S3 and vCluster set their own
Gateway and identity settings.

## Network and service checks

Network probes use controlled HTTP targets and wait for policy convergence.
A blocked connection must fail with a connection error or timeout; HTTP, DNS,
and command errors fail the test. The external target is `https://www.iana.org/`.
A peer outside the team namespaces checks denied ingress. Server-side dry runs
check host LimitRange defaults and all four CPU and memory quota fields.

Data probes use the runtime Service and check writable and read-only access
after credential and configuration changes.

S3 installs Contour and Keycloak. Its boto3 client uses `s3-credentials.py` as
`credential_process`. The test pauses the Keycloak client, changes its source
Secret, and checks credential propagation, sanitized observer status, and
workload restart. It restores the Secret, resumes the client, and repeats the S3 checks. The Keycloak credential itself
is unchanged.

Database probes run in `workspace`, where connection Secrets are published.
The test policies allow labeled service probes on PostgreSQL, MongoDB, and Redis
ports and block other outside clients. Operators and CRDs use the versions in
the [installation guide](../../docs/how-to-guides/installation.md#prerequisites).

## Volume checks

`verify-volumes` prepares the shared Keycloak test realm, then declares a
Datalab with named host storage and no virtual cluster. The Datalab must become
ready after the first PVC mount. Each volume gets a backup schedule. The profile
runs Jobs from the generated CronJob. The default retention must leave exactly
two ready snapshots.

The profile checks:

- Actual file recovery after the source changes, and independent writes to the
  restored PVC.
- Two ready recovery points for the current PVC UID; unrelated snapshots remain.
- Completed recovery points after a failed Job, and incomplete snapshot cleanup
  before another successful backup.
- Backup identity denial for PVC deletion, Secret reads, and snapshots in
  another namespace.
- The observed PVC reference and phase, ready-snapshot count, and last successful
  time in Datalab status.
- Independent backup schedules for source and restored volumes; volume removal
  removes its schedule and preserves the other volume.
- Recovery from a snapshot after the source volume declaration and PVC are removed.

These checks use the selected test cluster API because the resources being
tested are host resources. They do not install resources through a separate
physical host API when the selected target is a virtual cluster.

## Virtual cluster checks

The profile installs PGO, Keycloak, and Contour and creates a fresh certificate
for `*.lab.acme.com`. Its CPU limit quota is `20` so two control planes, their
controllers, DNS, PostgreSQL, and the catalog can perform rolling updates.

The `test-login` client uses generated passwords to obtain user tokens.
Checks cover members, administrators, unauthorized profiles, exact roles and
audiences, and rejection of interactive scopes during token exchange.

The workspace service account starts with `ws_api` only. The test assigns
individual vcluster roles and requests their optional scopes. It checks
namespace access, denied escalation, role downgrade, and revocation of tokens
that have not expired. Downloaded helpers must return the caller token unchanged.

Storage checks create an application PVC through the virtual API and mount it in ordinary Pods. Workload
replacement, vCluster hibernation, and control-plane restart must keep the
same claim and files. Oversized virtual Pods must report host CPU and memory
quota rejection. Controller installation uses only the virtual API.

Named-volume checks mount a Datalab host PVC through an explicit binding.
Virtual claim replacement and binding removal must keep file contents, the host
PVC UID, the backup schedule, and a ready snapshot. Host admission must preserve
read-only mounts and other Pod volumes. Removing `vc0` with a running bound Pod
must finish and keep the host volume and its backups. If the snapshot probe
fails on an existing target, these named-volume checks are skipped. The profile
still checks ordinary application PVCs, authentication, routing, and lifecycle.

Other checks cover OAuth2 discovery, source Secret deletion and recovery,
and separate custom Secrets for users. STAC item search must still work
after both instances hibernate and resume and after a control-plane restart.
Hibernation must remove their synced Pods, keep the same PVCs, and leave PostgreSQL
ready. Removing one virtual cluster must leave the
other cluster and PostgreSQL available.

## Test resource budget

A full run shares one selected cluster. Unused database operators are scaled to zero.
Each store profile starts its operator and waits for readiness. Cleanup waits for
resource deletion before stopping the operator; failures leave it running.
Crossplane, providers, storage, and identity services stay available.

The runner reports durations and CPU requests. Use
`tests/integration/resource-budget.bash` to inspect scheduled and pending
requests. Probe and backup execution timeouts start after scheduling.
Failures report events and the resource budget.

Integration builds a separate Composition artifact with a `1m` Python TTL default.
Environment overrides and the separate environment and auto-ready TTLs still
apply. See [build settings](../../templates/README.md).

## GitHub Actions

The [workflow](../../.github/workflows/pr.yaml) uses the
[shared check selection](../README.md#select-checks). Runtime changes and manual
runs execute the full unit suite and all nine profiles in one Kind cluster.
Draft pull requests run the unit suite but defer Kubernetes integration;
marking the pull request ready enables it. Documentation-only changes run
documentation and static checks. The final required check waits for every
selected job.

Tag publication requires a successful push test run for the tagged commit and
does not repeat tests. Use tags such as `1.0.0`, without a `v` prefix.
