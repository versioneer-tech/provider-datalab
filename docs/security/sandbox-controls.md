# Network policies

Provider Datalab creates ingress and egress policies in the Datalab-named host
service namespace. This namespace is the team boundary. Services, virtual
control planes, and synced workload Pods use it regardless of their virtual
namespace. Virtual clusters in one Datalab share this boundary.
The cluster CNI must enforce Kubernetes NetworkPolicy for these rules to take
effect.

NetworkPolicies inside a virtual cluster are not synced to the host. Configure
team network access through EnvironmentConfig. The generated host policies
permit same-team traffic; they do not isolate workloads within a team.

## Generated namespace policies

| Policy | Created when | Allows |
| --- | --- | --- |
| `deny-ingress` | By default | No ingress by itself; service and explicit internal rules can allow traffic. |
| `allow-namespace-ingress` | By default | Traffic from Pods in the same host service namespace. |
| `deny-egress` | By default | No egress by itself; other policies can allow traffic. |
| `allow-namespace-egress` | By default | Traffic to Pods in the same runtime namespace. |
| `allow-dns-egress` | External egress, Data, registry, or vCluster is enabled | DNS to `kube-system` on TCP and UDP port 53. |
| `allow-external-egress` | External egress is enabled | The configured external CIDRs, minus excluded ranges. |
| `allow-internal-egress` | Internal targets are configured | The selected backend Pods and ports in other namespaces. |
| `allow-internal-ingress` | Internal sources are configured | The selected source Pods and ports from other namespaces. Target selectors can limit the receiving Pods. |

The DNS rule lets Data and the registry resolve storage hosts and lets
workloads resolve their vCluster Service. Same-namespace rules permit access
to the Datalab's virtual API.

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

With external egress disabled, same-namespace traffic, DNS needed by Data, registry, or
vCluster, and access to the Datalab's vCluster API remain allowed.
Standard NetworkPolicy cannot express ordered deny rules or DNS-name rules.

## Service policies

For internal access, packageR accepts port 8888 from Pods in the service namespace.
For permanent access, its OAuth proxy accepts port 4180. See
[Data and sharing](../how-to-guides/usage_concepts.md#data-and-sharing) for
browser access and public links.

The S3 service accepts Gateway traffic on port 8080. Data and S3 proxies can
reach IAM on TCP port 8080 in the configured IAM namespace. Object-storage
access follows the Datalab's egress rules. Set `iam.namespace` to the namespace
that contains the Keycloak Pods.

The registry accepts TCP port 5000. Its health port is not exposed by the
Service or public routes. Object-storage access uses the Datalab's egress rules.

Each virtual API accepts ingress on TCP port 8443 for authenticated Kubernetes
access through the Gateway. Its workload and DNS policies permit the required
control-plane traffic. These allowances add to the namespace policies.

## Replace or exclude policies

Use `EnvironmentConfig.data.network.excludePolicies` only when another policy
system provides the required controls. Excluding `allow-dns-egress` also
suppresses the Data DNS policy.

Use RBAC and admission rules to limit who can change NetworkPolicies or
select privileged and admin settings.
