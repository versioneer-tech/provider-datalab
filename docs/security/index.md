# Security

A session can use the credentials, volumes, Kubernetes permissions, and
network access available to its Pod. The platform operator decides which
users may start sessions and which resources they may use.

Provider Datalab passes session security settings to Educates and creates
network policies. Educates creates the workspace Pods and applies the
namespace, role, and token settings. The cluster must enforce them through
its CNI, admission rules, Pod security, and RBAC.

## Access to a Datalab

The ingress controller must handle session sign-in and authorization.
Provider Datalab creates Keycloak clients, groups, and roles for each Datalab.
Users receive `ws_access` or `ws_admin`; the client service account receives
`ws_api` for machine access.

Shared browser ingress can use one platform OAuth client and check the
Datalab roles for each requested host. Services belonging to one Datalab can
use its generated client. See [Authentication](../how-to-guides/authentication.md)
for the client model and controller examples.

Anyone who can read the runtime `<datalab>-oauth2-client` Secret can request
machine tokens for that Datalab. Limit Secret access to the users and
services that need it, and rotate credentials when access changes.

Public Data shares allow browsing and downloads without sign-in. Users
should place only files they intend to publish in the Datalab's `public`
folder. See [Public sharing](../how-to-guides/usage_concepts.md#sharing-data-with-the-world).

## Session defaults

| Setting | Default | Effect |
| --- | --- | --- |
| `spec.security.policy` | `baseline` | Selects the Educates namespace security policy. `privileged` also enables Docker. |
| `spec.security.kubernetesAccess` | `true` | Makes a Kubernetes service account token available to the session. |
| `spec.security.kubernetesRole` | `edit` | Sets the session's Kubernetes permissions. |
| `spec.security.externalEgress` | `true` | Enables the external egress rule for the configured CIDRs. |
| `spec.vcluster` | `false` | Uses the host namespace directly. When enabled, adds a virtual Kubernetes API. |

Set shared security defaults in `EnvironmentConfig.data.defaults.security`.
Use stricter values when workspace code does not need Kubernetes access,
external traffic, or privileged containers. A vCluster changes the Kubernetes
API available to users; its Pods still run on the host cluster.

## Platform responsibilities

The platform team manages ingress authentication, the CNI, admission rules,
RBAC, DNS, storage classes, quotas, and node access. It also manages cloud
IAM, bucket policy, backup, retention, and audit for the data and services
available to a Datalab.

NetworkPolicy rules are additive. Another policy can allow traffic that the
generated policies do not allow. Standard NetworkPolicy also cannot express
ordered deny rules or domain-name allowlists. Check the combined rules in
the deployed cluster.

Privileged containers, host mounts, runtime sockets, and broad credentials
can give workspace code access beyond its namespace. Approve those settings
only for users and workloads that need them. Replacing a Pod or tightening a
network rule does not revoke a leaked credential; rotate or revoke it at its
source.

[Session access](workspace-sessions.md) describes what workspace code can use.
[Network policies](sandbox-controls.md) lists the generated policies and the
settings that control them.
