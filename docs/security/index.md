# Security

A Datalab combines identity, data connections, storage, network policies, and
an optional virtual Kubernetes API. The platform controls who can create or
change Datalabs, resolve connection Secrets, and select privileged settings.

The main Keycloak client provides Data access. Vcluster profiles use separate
clients and roles. Workspace roles grant no virtual Kubernetes permissions.
See [authentication](../how-to-guides/authentication.md).

The service namespace uses `EnvironmentConfig.data.defaults.security.policy`,
with `baseline` as the default. Vcluster shares this namespace and its Pod security policy. Virtual
administrator permissions do not grant host cluster administration, but
workloads still share host nodes and kernels.

The CNI must enforce NetworkPolicy. Rules are additive: another policy can
allow traffic that a generated policy omits. Operators manage host admission,
RBAC, storage classes, DNS, node security, backups, and credential rotation.

Keep input and connection Secrets under operator-controlled access. A profile
kubeconfig contains a client credential. Rotate or revoke exposed credentials
at their source; changing a Pod or network rule does not revoke them.

Public Data shares allow browsing and downloads without sign-in. Put only
intended public data in the shared folder. Internal package-r access trusts
its caller's identity header and needs explicit ingress controls.

See [workload access](workload-access.md), [network policies](sandbox-controls.md),
and [vcluster access](../how-to-guides/vcluster.md).
