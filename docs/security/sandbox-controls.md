# Network policies

Provider Datalab creates egress and Data policies in the Datalab namespace.
The cluster CNI must enforce Kubernetes NetworkPolicy for these rules to take
effect.

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

Supply the host Pod and Service CIDRs so that broad external egress does not
also grant access to other Datalab namespaces. The rule excludes these ranges
and the configured blacklist. Use explicit internal rules for required
backends in other namespaces. See [Network access](../how-to-guides/installation.md#network-access)
for setup examples and the [network reference](../how-to-guides/installation.md#network-rules)
for all fields.

With external egress disabled, same-namespace traffic, DNS needed by Data or
vCluster, and access to the Datalab's vCluster API remain allowed.
Standard NetworkPolicy cannot express ordered deny rules or DNS-name rules.

## Data service policies

For session access, packageR accepts port 8888 from session Pods.
For permanent access, its OAuth proxy accepts port 4180. See
[Data and sharing](../how-to-guides/usage_concepts.md#data-and-sharing) for
browser access and public links.

The S3 service accepts Gateway traffic on port 8080. Data and S3 proxies can
reach IAM on TCP port 8080 in the configured IAM namespace. Object-storage
access follows the Datalab's egress rules. Set `iam.namespace` to the namespace
that contains the Keycloak Pods.

## Replace or exclude policies

Use `EnvironmentConfig.data.network.excludePolicies` only when another policy
system provides the required controls. Excluding `allow-dns-egress` also
suppresses the Data DNS policy.

Use RBAC and admission rules to limit who can change NetworkPolicies or
select privileged and admin settings.
