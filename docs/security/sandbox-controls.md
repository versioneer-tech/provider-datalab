# Sandbox Security Measures

Provider Datalab should describe the controls it actually creates, then point
to planned hardening separately. Today the main shipped controls are Educates
namespace security settings, Kubernetes RBAC/token settings, and a generated
namespace-level NetworkPolicy set. Operators should treat these as the default
baseline to validate, not as a substitute for platform admission policy,
backup policy, identity governance, and audit.

## Current Educates Integration

Provider Datalab renders an Educates `Workshop` and `WorkshopEnvironment`.
The Datalab security fields are passed into the Educates session namespace
configuration:

- `spec.security.policy` -> Educates namespace security policy
- `spec.security.kubernetesAccess` -> token enabled or disabled
- `spec.security.kubernetesRole` -> namespace or vcluster role
- `policy: privileged` -> enables the Educates Docker application with extra
  local storage

This keeps Provider Datalab aligned with Educates instead of duplicating a
separate Pod launcher.

## Current NetworkPolicy Baseline

Provider Datalab injects generated `NetworkPolicy` objects into the Educates
environment objects. They select all Pods in the runtime namespace.

- `deny-egress` and `allow-namespace-egress` are rendered by default.
  Together they deny egress first, then allow traffic to Pods in the same
  runtime namespace.
- `allow-dns-egress` and `allow-external-egress` are rendered only when
  `externalEgress` is true.
- `allow-internal-egress` is rendered when `EnvironmentConfig.data.network.internalEgress`
  contains explicit backend targets. It allows operator-approved Pods in other
  namespaces through namespace and pod selectors.
- `spec.security.externalEgress` falls back to
  `EnvironmentConfig.data.defaults.security.externalEgress`, then to the hard
  default `true`.
- `EnvironmentConfig.data.network.externalEgressCIDRs` is the external egress
  allowlist. Operators can use `0.0.0.0/0` and `::/0` for open external
  IPv4/IPv6 egress, or narrower platform-approved ranges. If the list is empty
  or omitted, no broad external allow block is rendered, even though
  `externalEgress` defaults to `true`.
- `EnvironmentConfig.data.network.blacklistIPs` lists CIDRs excluded from broad
  external egress, for example AWS EC2 and Scaleway metadata IPv4/IPv6
  endpoints.
- `EnvironmentConfig.data.network.podCIDRs` and `serviceCIDR` are also excluded
  from broad external egress. This keeps other runtime namespaces unreachable
  by PodIP or ServiceIP unless an operator adds an explicit allow policy.

`deny-egress` is the default-deny base policy, so it blocks all egress unless
another selected policy also allows it.

`allow-namespace-egress` allows Pod-to-Pod traffic inside the same runtime
namespace, which is why the workshop can still reach its own namespace-local
Pods.

`allow-dns-egress` allows DNS lookups to `kube-system` on TCP and UDP port 53,
and it is only rendered when `externalEgress` is true.

`allow-external-egress` allows outbound traffic to the CIDRs in
`externalEgressCIDRs`, minus the excluded ranges from `blacklistIPs`,
`podCIDRs`, and `serviceCIDR`.

`allow-internal-egress` allows explicit backend Pods in other namespaces,
using the namespace and pod selectors configured in
`EnvironmentConfig.data.network.internalEgress`.

A CIDR is just IP-range notation, such as `10.42.0.0/16`, which means "all IPs
in that block." Kubernetes `NetworkPolicy` works with IP blocks, so Provider
Datalab configures explicit CIDRs instead of a separate "cluster internal"
label.

The system cannot auto-detect "cluster internal" in a portable way because
Kubernetes does not expose a universal internal-vs-external egress concept and
Pod/Service ranges vary by cluster, CNI, and dual-stack setup. That is why the
operator supplies `podCIDRs` and `serviceCIDR`.

The closest upstream convention is the standardized namespace label
`kubernetes.io/metadata.name`, which lets a `namespaceSelector` target a
specific namespace by name. Kubernetes does not define a standard label such as
`internal=true` for services or workloads, so any "internal service" label
scheme is an operator convention, not a Kubernetes one.

With `externalEgress: false`, the generated policies do not allow DNS or
external network access. Cross-namespace traffic is not allowed by default;
operators should add a separate NetworkPolicy for explicit cross-namespace
dependencies.

NetworkPolicies are additive: if any selected egress policy allows traffic, the
traffic is allowed. Generated policies can be skipped with
`EnvironmentConfig.data.network.excludePolicies`, but this is an exceptional
operator escape hatch for clusters that replace the generated baseline with
their own policy set.

## Operator Checks

For the current baseline, operators should verify and be able to explain:

- the installed CNI enforces Kubernetes NetworkPolicy
- `externalEgress` defaults match the platform trust model
- `blacklistIPs` includes the cloud metadata and platform-control CIDRs that
  must not be reachable through broad external egress
- any cross-namespace dependencies have explicit, operator-owned policies
- `excludePolicies` is used only when another policy system supplies equivalent
  controls
- `kubernetesAccess` and `kubernetesRole` defaults match the platform trust
  model
- privileged/Docker/registry workflows are limited to trusted Datalabs

## Hardening Direction

The next implementation step is not to publish a long policy catalogue in user
docs. It is to turn the current compatibility baseline into small, testable
implementation steps:

- decide whether a future stricter profile should replace the current
  `externalEgress: true` compatibility default
- add profile-specific allows for DNS, central ingress, storage, and optional
  Kubernetes API access
- add admission policy, for example Kyverno, to prevent tenants from weakening
  generated NetworkPolicies or selecting privileged/admin settings without
  operator approval
- document and validate the Educates install settings that must be aligned
  with Provider Datalab
