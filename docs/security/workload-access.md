# Workload access

The platform controls who may start workloads and which connections and
volumes they receive.

A workload can use every credential, volume, network path, and Kubernetes
permission made available to its process. Mount only its approved connections.
Do not distribute the private vcluster recovery kubeconfig used by the
provider. Downloaded profile kubeconfigs use separate OAuth credentials.

Namespace profiles receive `view`, `edit`, or `admin` permissions through a
RoleBinding. Cluster administrator profiles use `namespace: "*"` and a
ClusterRoleBinding. Kubernetes RBAC enforces the boundary; a context namespace
is only a client default.

Virtual PVCs use only classes listed in
`EnvironmentConfig.data.vcluster.storageClasses.allowed`. The host admission
policy enforces this list even if a virtual administrator creates another
StorageClass. Users create and manage workload PVCs inside the virtual
cluster. Plan backups for these volumes and managed database volumes.
