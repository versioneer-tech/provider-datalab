# Session access

Workloads created in a virtual cluster run as Pods in the host cluster. They
can use their service credentials, workspace PVCs, and other mounted volumes.
Check these permissions together when deciding which code a user may run.
Sandboxd commands use the permissions and mounts of the sandboxd container.

## Kubernetes and container access

Namespace profiles receive `view`, `edit`, or `admin` permissions through a
RoleBinding. Cluster administrator profiles use `namespace: "*"` and a
ClusterRoleBinding. Kubernetes RBAC enforces access; a context namespace is
only a client default. Downloaded profiles use caller tokens. Keep the
provider's private recovery kubeconfig under operator control.

The sandboxd template disables automatic service account token mounting and
runs as a non-root user. Workloads remain subject to the host's Pod security,
network policies, and resource quota. The host service namespace is the team
boundary across all virtual clusters in a Datalab.

Host mounts, runtime sockets, broad roles, and privileged containers can give
workload code access beyond its namespace. Give this access only to workloads
that need it. See the
[configuration reference](../how-to-guides/installation.md#runtime-and-service-defaults)
for the settings and defaults.

Virtual PVCs use only classes listed in
`EnvironmentConfig.data.vcluster.storageClasses.allowed`. Host admission
enforces this list even if a virtual administrator creates another StorageClass.

## Explain access to users

Tell users which data and services a workload can use, whether Kubernetes
and internet access are available, and whether privileged workloads are
allowed. Explain what survives workload replacement or deletion, what is
backed up, and who can restore it.

Stopping a Pod or tightening a network rule does not revoke a leaked
credential. Rotate or revoke it at its source. Protect the OAuth client Secret
as described in [Authentication](../how-to-guides/authentication.md#credential-secrets-and-machine-access).
