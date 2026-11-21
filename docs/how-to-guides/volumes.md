# Use volumes

Declare named volumes under `spec.volumes`, as you declare named PostgreSQL
and Redis services. Each entry creates a `PersistentVolumeClaim` (PVC) in a
virtual cluster. Applications mount the claim and manage their own workloads.

```yaml
apiVersion: versioneer.at/v1
kind: Datalab
metadata:
  name: s-joe
  namespace: workspace
spec:
  users: [joe]
  vclusters:
    vc0:
      storage: 5Gi
  volumes:
    analysis:
      vcluster: vc0
      namespace: demo
      storage: 2Gi
```

The provider creates PVC `demo/volume-analysis` inside `vc0`. The size defaults
to `defaults.volumes.storage`, or `1Gi`. The PVC uses the virtual cluster's
default allowed StorageClass, filesystem volume mode, and `ReadWriteOnce`.
Its request counts toward the Datalab's host storage quota.

`status.volumes` reports the volume name, virtual cluster, namespace, and
PVC name. A volume cannot move to another virtual cluster or namespace. Its
declaration creates storage without starting an application.

## Mount a volume

Obtain a [virtual cluster profile](vcluster.md#api-access). After that handoff,
application installation and operation use the virtual API. Set the explicit
kubeconfig and context for that cluster:

```bash
volume_kubeconfig=/path/to/s-joe-vc0.kubeconfig
volume_context="$(kubectl --kubeconfig "$volume_kubeconfig" config current-context)"
kubectl --kubeconfig "$volume_kubeconfig" --context "$volume_context" \
  --namespace demo get pvc --selector datalabs.versioneer.at/volume=analysis
```

Mount the existing claim in a Pod or workload controller:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: volume-reader
  namespace: demo
spec:
  automountServiceAccountToken: false
  restartPolicy: Never
  securityContext:
    runAsNonRoot: true
    runAsUser: 1000
    runAsGroup: 1000
    fsGroup: 1000
    seccompProfile:
      type: RuntimeDefault
  containers:
  - name: reader
    image: busybox:1.36.1
    command: [sh, -c, 'ls /workspace; sleep 3600']
    securityContext:
      allowPrivilegeEscalation: false
      capabilities:
        drop: [ALL]
    volumeMounts:
    - name: workspace
      mountPath: /workspace
  volumes:
  - name: workspace
    persistentVolumeClaim:
      claimName: volume-analysis
```

Apply the manifest with the same kubeconfig and context. `ReadWriteOnce`
permits mounts on one node; it does not give each writer a separate copy or
prevent concurrent writes from Pods on that node. Use separate volumes for
independent tasks.

Application owners install their controllers, CRDs, templates, and images.
Installing CRDs and cluster RBAC requires virtual cluster administration.
Namespace roles can operate the installed resources when RBAC grants access.
Provider Datalab supplies no application controller or runtime templates.

Keep the PVC independent of application owner references. Replacing a Pod or
removing an application must preserve the claim and its namespace. Workloads
remain subject to the [platform access and security rules](../security/workload-access.md).

## Enable backups

The operator must enable [CSI snapshot support](installation.md#volume-snapshots)
before a volume can request backups:

```yaml
spec:
  volumes:
    analysis:
      vcluster: vc0
      namespace: demo
      storage: 2Gi
      backup: true
```

The provider creates a backup CronJob in the volume's virtual namespace. The
default schedule is daily at 01:00 UTC, with four completed snapshots retained.
`status.volumes[].backupCronJobName` identifies the CronJob. This reference
reports configuration, not a successful backup.

The source PVC must be `Bound`. A StorageClass with `WaitForFirstConsumer`
needs a workload that uses the claim before the first backup.

Each run creates a CSI `VolumeSnapshot`, waits for `readyToUse`, then removes
older completed snapshots for the same PVC UID. A failed run keeps the earlier
completed snapshots. Before another attempt, the Job removes incomplete
snapshots for that PVC UID and waits for pending snapshot deletion. This also
cleans up attempts left by an interrupted Job. A failed storage cleanup blocks
new snapshots until the operator resolves it.

There is no second backup PVC. CSI allocates storage for snapshots through the
configured `VolumeSnapshotClass`.
Snapshot storage does not count toward the PVC storage-request quota. The
operator must set and monitor storage-backend limits separately.

Check Job failures and snapshot readiness through the virtual API:

```bash
kubectl --kubeconfig "$volume_kubeconfig" --context "$volume_context" \
  --namespace demo get cronjobs,jobs
kubectl --kubeconfig "$volume_kubeconfig" --context "$volume_context" \
  --namespace demo get volumesnapshots \
  --selector datalabs.versioneer.at/volume=analysis
```

The scheduler runs inside the virtual cluster. It cannot take new backups
while that cluster is hibernated. CSI snapshots capture volume state; an
application may need to flush or stop writes for a consistent recovery point.
They do not include Kubernetes objects or managed database data. Arrange
control-plane recovery and independent disaster backups with the operator.

PostgreSQL, MongoDB, and Redis use their own `backupStorage` setting and backup
tools. A volume's `backup` setting applies only to its PVC; see
[managed service backups](usage_concepts.md#backups).

## Restore into a new volume

Select a snapshot with `readyToUse: true` in the same virtual namespace. Declare
a new volume with its snapshot name and a size at least as large as the source:

```yaml
spec:
  volumes:
    recovered-analysis:
      vcluster: vc0
      namespace: demo
      storage: 2Gi
      restoreFrom: volume-analysis-example
```

Use the actual snapshot name in place of `volume-analysis-example`. The provider
creates `demo/volume-recovered-analysis` with that snapshot as its data source.
The source is fixed when the volume is created. Mount the new claim to check
its files before using it. Restore does not change an existing volume.

## Remove storage

Removing a volume entry deletes its PVC. Stop workloads that mount it first.
Disabling `backup` removes the schedule and its RBAC but keeps existing
snapshots. Removing a volume also keeps its snapshots while their namespace
and virtual cluster remain. Automatic retention ends when its schedule ends.

Deleting the virtual namespace, virtual cluster, or Datalab can delete the
snapshot objects and their underlying storage. Keep an independent backup
before deleting that boundary. See the upstream
[volume snapshot documentation](https://kubernetes.io/docs/concepts/storage/volume-snapshots/).
