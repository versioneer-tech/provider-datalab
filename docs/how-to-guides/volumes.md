# Use volumes

Declare persistent volumes under `spec.volumes`. Each volume has a PVC and
backup schedule in the Datalab host namespace. Virtual cluster removal does
not remove these volumes.

```yaml
apiVersion: versioneer.at/v1
kind: Datalab
metadata:
  name: s-joe
  namespace: workspace
spec:
  users: [joe]
  volumes:
    demo:
      storage: 2Gi
```

This creates host PVC `s-joe/volume-demo` and its snapshot schedule.
The size defaults to `EnvironmentConfig.data.volumes.storage`, or `1Gi`.
The PVC uses filesystem volume mode and `ReadWriteOnce`. The operator selects
the allowed classes with `EnvironmentConfig.data.volumes.storageClasses.allowed`.
`volumes.storageClasses.default` selects the class for named volumes and virtual
workloads; without that setting, the first allowed class applies. The allowlist
must be non-empty when volumes or virtual clusters are declared.
The request counts toward the Datalab's host storage quota.

The operator must configure [snapshot infrastructure](installation.md#volume-snapshots).
To use the volume through a virtual API, add a binding as shown below.

## Check status

```yaml
status:
  volumes:
    - name: demo
      pvcRef:
        namespace: s-joe
        name: volume-demo
      phase: Bound
      backup:
        readySnapshots: 2
        lastSuccessfulTime: '2026-11-21T01:00:00Z'
```

`phase` is the observed PVC phase: `Pending`, `Bound`, or `Lost`.
A class with `WaitForFirstConsumer` keeps the claim Pending until a workload
uses it. Datalab readiness does not require a consumer to bind the claim.

`readySnapshots` counts snapshots available for the current PVC, excluding
pending, failed, and deleting snapshots. `lastSuccessfulTime` is the creation
time of the latest ready snapshot. It is absent until one is available.

## Bind to a virtual cluster

Add a binding to `vc0`. `name` selects the source from `spec.volumes`; `target`
sets the PVC name and namespace in the virtual cluster:

```yaml
spec:
  volumes:
    demo:
      storage: 2Gi
  vclusters:
    vc0:
      volumeBindings:
      - name: demo
        target:
          namespace: demo
          name: demo
```

The provider creates virtual namespace `demo` and PVC `demo/demo`, backed by
the existing host PVC `s-joe/volume-demo`. The binding allocates no second volume.
Each named volume can have one binding. PVC targets must be unique within each
virtual cluster. The host needs Kubernetes 1.36 or later with
[mutating admission support](vcluster.md#host-requirements).

Save the [mount Pod example](https://github.com/versioneer-tech/provider-datalab/blob/main/examples/vcluster/volume-pod.yaml)
as `volume-pod.yaml`. Use the downloaded virtual kubeconfig:

```bash
kubectl --kubeconfig ./s-joe-vc0.kubeconfig apply -f volume-pod.yaml
kubectl --kubeconfig ./s-joe-vc0.kubeconfig -n demo \
  wait pod/volume-demo --for=condition=Ready --timeout=5m
kubectl --kubeconfig ./s-joe-vc0.kubeconfig -n demo exec volume-demo -- \
  sh -c 'printf "saved\n" > /data/message'
kubectl --kubeconfig ./s-joe-vc0.kubeconfig -n demo exec volume-demo -- cat /data/message
```

Application installation and file access need only virtual cluster credentials.
The complete Datalab is in the
[virtual cluster example](https://github.com/versioneer-tech/provider-datalab/blob/main/examples/vcluster/datalab.yaml).
`ReadWriteOnce` permits mounts on one node; it does not prevent concurrent
writes from Pods on that node. Use separate volumes for independent data.

Deleting the Pod, virtual PVC, binding, or virtual cluster preserves the host
PVC and its backups while `spec.volumes.demo` remains. A deleted virtual PVC is
recreated and rebound while its binding remains. Stop workloads before removing
or changing their binding. Removing a binding removes its virtual PV and PVC
records after consumers release them.
The control plane waits for the required host policies before it starts.
Binding policies remain until the virtual claim Object is removed. Wait for
the old binding policies to be deleted before you use the same target again.

### Direct host mounts

A host workload in the Datalab service namespace can use
`persistentVolumeClaim.claimName: volume-demo`. Keep the host claim independent
of application owner references. Removing an application must preserve it.

## Backup policy

The operator sets one policy in EnvironmentConfig:

```yaml
data:
  volumes:
    storage: 1Gi
    storageClasses:
      allowed: [workspace-storage]
      default: workspace-storage
    snapshotClassName: workspace-snapshots
    schedule: '0 1 * * *'
    maxSnapshots: 2
```

The default schedule is daily at 01:00 UTC, with two completed snapshots kept
for the current PVC UID. `maxSnapshots` accepts an integer from 1 to 100.
The policy applies to every named volume, including restored volumes.

The backup CronJob runs on the host. It continues when virtual clusters are
hibernated or removed. It does not mount the source volume. The source PVC
must be Bound before a backup can succeed.

Each run creates a CSI snapshot and waits for it to become ready before it
removes older recovery points for the same PVC. Failed runs preserve completed
backups. Incomplete attempts must be removed before another snapshot starts.

The PVC uses a `StorageClass`; its snapshots use a `VolumeSnapshotClass` with
the same CSI driver. Snapshots need no second PVC or StorageClass. Their storage
does not count toward the PVC request quota; monitor backend capacity separately.

Successful daily backups leave up to 24 hours between recovery points.
Failures extend that gap. Set a shorter interval when needed. Applications may
need to flush or pause writes for a consistent recovery point. Managed databases
use their own [backup tools](usage_concepts.md#backups).

Check failed Jobs and snapshot readiness in the host service namespace.
CSI snapshots do not include Kubernetes objects and may share the volume's
storage failure boundary. Arrange an independent backup and test restores
before relying on the recovery policy.

## Restore into a new volume

Select a ready snapshot in the Datalab host namespace. Add a new entry alongside
the existing volume. Set `storage` to at least the snapshot's `status.restoreSize`:

```yaml
spec:
  volumes:
    recovered-demo:
      storage: 2Gi
      restoreFrom: volume-demo-example
```

Use the actual snapshot name. The provider creates
`s-joe/volume-recovered-demo` from that snapshot. The restore source is fixed
at creation. Restore does not overwrite an existing volume. Check the restored
files before using the new PVC.

## Remove storage

Stop workloads, remove their volume binding, then remove the volume entry.
Removing the entry deletes the host PVC, its snapshot schedule, and its backup permissions.
Completed snapshots remain in the Datalab namespace; automatic retention stops
with the schedule.

Deleting the Datalab or its host namespace deletes that storage boundary and can
delete snapshots and their data. Keep an independent backup before deletion.
