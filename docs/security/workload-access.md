# Workload access

Workloads created in a virtual cluster run as Pods in the host cluster. They
can use their mounted credentials, PVCs, and other volumes. Check these
permissions together when deciding which code a user may run.

## Kubernetes access

Namespace profiles receive `view`, `edit`, or `admin` permissions through a
RoleBinding. Cluster administrator profiles use `namespace: "*"` and a
ClusterRoleBinding. Kubernetes RBAC enforces access; a context namespace is
only a client default. Downloaded profiles use caller tokens. Keep the
provider's private recovery kubeconfig under operator control.

Application owners can install controllers and CRDs with virtual cluster
administration credentials. Their controllers use virtual ServiceAccounts.
Application installation does not require host cluster credentials. The
platform operator controls which host capabilities the virtual cluster exposes.

Clients can port-forward through the virtual API. RBAC controls
`pods/portforward` access, not individual port numbers. Reconnect when a Pod
stops or is replaced. Kubernetes authenticates this connection; direct Pod
traffic needs the application's own authentication when required.

## Platform boundary

The host service namespace is the team boundary across all virtual clusters
in a Datalab. Host Pod security, network policies, and resource quota apply to
synced workloads. Virtual namespaces do not create separate host networks.

Host mounts, runtime sockets, broad roles, and privileged containers can give
workload code access beyond its namespace. Grant only the access a workload
needs. Set application images, resource limits, security contexts, and token
mounting in the application package.

Virtual PVCs use only classes listed in
`EnvironmentConfig.data.vcluster.storageClasses.allowed`. Host admission
enforces this list even if a virtual administrator creates another StorageClass.
CSI snapshot synchronization requires additional host permissions for the
vCluster syncer. The operator enables it explicitly; application installers
continue to use only virtual credentials.

The volume snapshot ServiceAccount can read its source PVC and create,
read, list, and delete snapshots in that virtual namespace. It cannot delete
PVCs. It can read the configured snapshot class. Separate namespaces when
backup identities need separate snapshot access.

The shared host snapshot role is operator-owned. The provider can bind it to
enabled syncers but cannot change its rules. Application credentials do not
contain this host identity.

## Explain access to users

Tell users which data and services a workload can use, whether Kubernetes
and internet access are available, and whether privileged workloads are
allowed. Explain what survives replacement or deletion, what is backed up,
and who can restore it.

Stopping a Pod or tightening a network rule does not revoke a leaked
credential. Rotate or revoke it at its source. Protect the OAuth client Secret
as described in [Authentication](../how-to-guides/authentication.md#credential-secrets-and-machine-access).
