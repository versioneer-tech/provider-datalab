# Security

A virtual API uses caller token roles and Kubernetes RBAC. A downloaded
profile selects an endpoint and namespace; it grants no access. Virtual
workloads and sessions can use the credentials, volumes, permissions, and
network access available to their Pods.

The platform operator sets the
[EnvironmentConfig](../how-to-guides/installation.md#environmentconfig-values-and-defaults)
and decides who can use these resources. The host cluster must enforce network
policies, admission rules, Pod security, and RBAC. Virtual clusters share its
nodes and kernel.

| Control | Details |
| --- | --- |
| Caller roles, public profiles, and virtual RBAC | [Virtual API access](../how-to-guides/vcluster.md#api-access) |
| Browser sign-in, Datalab roles, and machine tokens | [Authentication](../how-to-guides/authentication.md) |
| Pod credentials, Kubernetes access, and privileged workloads | [Session access](workspace-sessions.md) |
| Allowed traffic and generated NetworkPolicies | [Network policies](sandbox-controls.md) |
| Files that readers can open without sign-in | [Public sharing](../how-to-guides/usage_concepts.md#sharing-data-with-the-world) |

The platform team also manages node access, DNS, storage classes, quotas,
cloud IAM, backup, retention, and audit. Check these controls together before
giving users access to a Datalab.
