# ADR-001: Use Datalab as the Public Contract

> Written: 02.12.2025. Revised: 21.11.2026.

## Status

Proposed. Design approval and runtime validation are pending.

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

### Use named volumes

`spec.volumes` is a map keyed by volume name, like the named managed
services. Each volume selects a virtual cluster, namespace, and optional size.
The provider creates a PVC with a stable name and reports its location in
`status.volumes`. The virtual PVC also has a volume label for discovery
without host API access.

Volumes use an allowed StorageClass and count toward the host storage quota.
The virtual cluster and namespace are fixed after creation. Workloads mount
the existing claim and must not add ownership that deletes the claim with
the runtime. Pod replacement and application removal preserve its storage.
Removing the volume declaration deletes the PVC after its users release it.

Application owners manage start, stop, runtime replacement, tasks, and access.
These choices do not belong in the storage declaration. Whole-cluster
hibernation remains under `spec.vclusters.<instance>.hibernated` and preserves
virtual resource definitions and PVCs.

### Protect volumes with optional CSI snapshots

The operator explicitly enables snapshot synchronization and supplies a
snapshot class. It requires a snapshot-capable CSI driver and host snapshot
infrastructure. Ordinary volumes do not require those prerequisites.

A volume with `backup: true` gets a virtual backup CronJob. Each run waits for
a new snapshot to be ready before pruning older completed snapshots for the
same PVC UID. The snapshot class uses deletion policy `Delete` so retention
can remove underlying snapshots. Disabling the schedule keeps its snapshots.
Incomplete attempts are removed before a new snapshot is created. Pending
deletion blocks new attempts. Snapshot Jobs stop during virtual cluster
hibernation. The operator owns the shared host snapshot role; the provider
binds it only to syncers with snapshot support enabled.

`restoreFrom` initializes a new volume from a ready snapshot in the same
virtual namespace. It cannot change after creation. The recovered PVC has its
own lifecycle. Application consistency may require a flush or pause coordinated
by the application owner. Control-plane backup and disaster recovery are
separate platform responsibilities.

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
- Snapshot prerequisites and additional syncer permissions are optional.
- Backup status and application health need their own operational checks.
- Local checks validate generated resources and backup failure behavior.
  Live checks must qualify storage, authorization, hibernation, and restore.
