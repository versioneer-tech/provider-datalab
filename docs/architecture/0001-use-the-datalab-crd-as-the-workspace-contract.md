# ADR-001: Use Datalab as the Public Contract

> Written: 02.12.2025. Revised: 21.11.2026.

## Status

Accepted. Live storage validation is pending.

## Context

A team needs persistent files, credentials, networking, virtual Kubernetes
clusters, and optional services. The platform needs a stable contract for
these resources. Applications need control of their own installation and
runtime lifecycle through the virtual Kubernetes API.

## Decision

### Use Datalab for team resources

Users and GitOps tools declare a namespaced `versioneer.at/v1` Datalab. It
contains team membership, named virtual clusters, managed services, and named
volumes. The operator-owned EnvironmentConfig sets platform
identity, network, storage, and security policy.

The Datalab name, namespace, and UID form its identity. Crossplane creates a
host service namespace with the Datalab name. Its quota, LimitRange, and
network policies apply to services and synced workloads.

The Datalab is the network boundary. Host policies restrict traffic between
Datalabs and permit shared networking within one Datalab, including across
its virtual clusters. A virtual cluster is an API boundary. Separate Datalabs
are required for separate team trust boundaries.

### Keep infrastructure and applications under separate owners

Crossplane owns the generated host resources, virtual cluster configuration,
identity settings, and declared storage. Application owners install CRDs,
controllers, RBAC, templates, pools, and runtime images through the virtual API.
Their installer needs suitable virtual permissions; it needs no host credentials.

Provider Datalab installs no application controller or default runtime. A
controller failure is an application health concern. Platform capabilities
such as storage drivers, host runtime classes, and network enforcement remain
under operator control.

### Use named host volumes

`spec.volumes` is a map keyed by volume name, like the named managed services.
Each entry creates a PVC in the Datalab host namespace. It selects a size and
an optional restore source. It has no virtual cluster or virtual
namespace field.

The PVC belongs to the Datalab and counts toward its host storage quota.
Applications must not add ownership that deletes it with a workload. Removing
a virtual cluster leaves the PVC unchanged. Removing the volume declaration
deletes the claim after its users release it.

Host volume provisioning and virtual workload attachment are separate concerns.
`spec.vclusters.<instance>.volumeBindings` selects a named volume and a target
virtual namespace and PVC name. Each source can have one binding; targets must
be unique within an instance.

The provider creates static virtual PV and PVC records marked for external
control. vCluster leaves these records unsynced. Host mutating admission directs
matching workload Pod mounts to the existing host PVC, without a second storage
allocation. The host needs Kubernetes 1.36 or later for the v1 policy API.
Host admission denies syncer changes to named host claims. Virtual admission
protects the binding label and static PV reference.

Removing a virtual PVC, binding, or cluster preserves the host PVC and backups
while the volume declaration remains. A deleted virtual PVC is recreated and
rebound while its binding remains. Applications use virtual credentials to
install and mount their workloads.

The virtual binding policy owns its PV and PVC records. The composition waits
for its UID before it creates those records; Kubernetes rejects an empty owner UID.
The virtual PVC waits for its PV so vCluster cannot create a conflicting placeholder.
Background garbage collection removes those records after unbinding without
holding virtual cluster removal. The virtual PV binder stays enabled to release
storage protection after consumers stop, including after the last binding is removed.

### Protect volumes with host CSI snapshots

The operator supplies a snapshot-capable CSI driver, the host snapshot
infrastructure, and a snapshot class.

Each named volume with `backups: true` gets a host backup CronJob. The default
is `false`. Disabling backups keeps the PVC and completed snapshots. The operator sets the
schedule and `maxSnapshots` in EnvironmentConfig. Defaults are daily at 01:00 UTC
and two completed snapshots per PVC UID. The snapshot limit is not a per-volume field.

Each run waits for a new snapshot to be ready before pruning older completed
snapshots for that PVC UID. Failed runs preserve completed recovery points.
Incomplete attempts are removed before a new allocation; unfinished deletion
blocks the run. The snapshot class uses deletion policy `Delete` so retention
can remove backend snapshots.

Backups run independently of virtual cluster state. The backup identity can
read its source PVC and manage snapshots in its host namespace. It can read
snapshot classes but cannot delete PVCs or read Secrets. Virtual cluster
syncers need no snapshot permissions.

`status.volumes` reports the host PVC reference and phase. Backup status reports
the number of ready snapshots and the latest successful snapshot time. It does
not expose scheduler names or individual snapshot references.

`restoreFrom` initializes a new host volume from a ready snapshot in the same
Datalab namespace. It cannot change after creation. The restored PVC has its
own lifecycle. Application consistency may require a flush or pause. Cluster
state backup and independent disaster recovery remain platform responsibilities.

### Keep credentials out of the public API

Credentials are read from referenced Secrets and copied only where needed.
Values do not belong in Datalab spec, status, logs, or normal client output.
Connection status reports Secret references. A downloaded virtual profile
uses caller authentication and virtual RBAC. The private recovery kubeconfig
stays under operator control.

Clients can use virtual Kubernetes port forwarding where RBAC permits it.
Application owners provide any direct or browser access their software needs.
Kubernetes API authentication does not authenticate direct Pod traffic.

## Consequences

- Datalab provides a stable contract for team infrastructure and storage.
- Applications can change their controllers and images independently.
- Persistent volumes can outlive the workloads that mount them.
- Named volumes require snapshot infrastructure and scoped backup permissions.
- Snapshot counts and age do not replace Job failure monitoring or restore tests.
- Local checks validate generated resources and backup failure behavior.
  Live checks must qualify storage, authorization, hibernation, and restore.
