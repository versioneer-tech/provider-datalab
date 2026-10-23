# Network policies

Provider Datalab creates egress policies through the Educates environment and
Data policies directly in the runtime namespace. The cluster CNI must enforce
Kubernetes NetworkPolicy for these rules to take effect.

## Session security

Provider Datalab passes these fields to Educates:

| Datalab field | Educates setting |
| --- | --- |
| `spec.security.policy` | Namespace security policy |
| `spec.security.kubernetesAccess` | Kubernetes token enabled or disabled |
| `spec.security.kubernetesRole` | Namespace or vCluster role |

The `privileged` policy also enables the Docker application with local
storage. Educates applies these settings when it creates session resources.

## Generated egress policies

| Policy | Created when | Allows |
| --- | --- | --- |
| `deny-egress` | By default | No egress by itself; other policies can allow traffic. |
| `allow-namespace-egress` | By default | Traffic to Pods in the same runtime namespace. |
| `allow-dns-egress` | External egress, Data, or vCluster is enabled | DNS to `kube-system` on TCP and UDP port 53. |
| `allow-vcluster-egress` | vCluster is enabled | TCP ports 443 and 8443 to the same Datalab's vCluster control-plane Pods. |
| `allow-external-egress` | External egress is enabled | The configured external CIDRs, minus excluded ranges. |
| `allow-internal-egress` | Internal targets are configured | The selected backend Pods and ports in other namespaces. |

The DNS rule lets Data resolve storage hosts and lets sessions resolve their
vCluster Service. Namespace and Pod selectors on the vCluster rule limit it
to the same Datalab.

NetworkPolicies are additive. `deny-egress` selects Pods for egress isolation;
it does not override an allow rule in another selected policy. Check all
policies that select a Pod when testing access.

## External and internal ranges

`spec.security.externalEgress` falls back to
`EnvironmentConfig.data.defaults.security.externalEgress`, then to `true`.
The external allow rule uses these EnvironmentConfig fields:

| Field under `data.network` | Purpose |
| --- | --- |
| `externalEgressCIDRs` | External destination ranges. An empty list grants no broad external access. |
| `blacklistIPs` | Ranges excluded from that rule, such as cloud metadata endpoints. |
| `podCIDRs` | Host Pod networks excluded from broad external access. |
| `serviceCIDR` | Host Service network excluded from broad external access. |

Use `0.0.0.0/0` and `::/0` to allow all external IPv4 and IPv6 destinations,
or list narrower ranges. Supply the actual host cluster ranges so that this
rule does not also grant access to other Datalab namespaces.

With `externalEgress: false`, the broad external rule is omitted. Same-namespace
traffic, DNS needed by Data or a vCluster, and access to the Datalab's vCluster
API remain allowed. Add `internalEgress` entries for required backends in
other namespaces. Each entry selects a namespace, Pods, and destination ports.
See [Network access](../how-to-guides/installation.md#network-access) for an example.

## Data service policies

For session access, packageR accepts port 8888 from Educates workshop Pods.
For permanent access, its OAuth proxy accepts port 4180. The file browser
requires sign-in; public shares permit browsing and downloads without it.

The S3 service accepts Gateway traffic on port 8080. Data and S3 proxies can
reach IAM on TCP port 8080 in the configured IAM namespace. Object-storage
access follows the Datalab's egress rules.

## Replace or exclude policies

Use `EnvironmentConfig.data.network.excludePolicies` only when another policy
system provides the required controls. Excluding `allow-dns-egress` also
suppresses the Data DNS policy.

Before changing these settings, verify the CNI, the allowed network ranges,
and every required cross-namespace connection. Restrict who can change
NetworkPolicies or request privileged and admin settings through the
platform's RBAC and admission policy.
