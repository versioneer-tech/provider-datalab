# Security

A session can use the credentials, volumes, Kubernetes permissions, and
network access available to its Pod. The platform operator decides who may
use them and sets the [EnvironmentConfig](../how-to-guides/installation.md#environmentconfig-values-and-defaults).

Provider Datalab passes session settings to Educates and creates network
policies. The cluster must enforce these controls through its CNI, admission
rules, Pod security, and RBAC.

| Control | Details |
| --- | --- |
| Browser sign-in, Datalab roles, and machine tokens | [Authentication](../how-to-guides/authentication.md) |
| Pod credentials, Kubernetes access, and privileged workloads | [Session access](workspace-sessions.md) |
| Allowed traffic and generated NetworkPolicies | [Network policies](sandbox-controls.md) |
| Files that readers can open without sign-in | [Public sharing](../how-to-guides/usage_concepts.md#sharing-data-with-the-world) |

The platform team also manages node access, DNS, storage classes, quotas,
cloud IAM, backup, retention, and audit. Check these controls together before
giving users access to a Datalab.
