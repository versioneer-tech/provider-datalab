# Security

Sandboxing is running code in an isolated environment. Sandbox security is the
set of controls that makes that isolation hold when users, notebooks, scripts,
or agents run inside the workspace. For a platform operator, it is also a
governance question: who may run code, what authority does that code get, and
which state can survive the session.

Provider Datalab does not invent a separate sandbox runtime. It builds on
Kubernetes and sandbox environments curated by tooling such as Educates. Other
Kubernetes-based sandbox runtimes may be integrated later, but the current
package is scoped to the Educates-based composition.

- Educates creates the workshop runtime, session namespaces, optional vcluster,
  IDE, terminal, Docker/registry applications, and workspace ingress.
- Provider Datalab passes security intent into Educates through
  `spec.security.policy`, `spec.security.kubernetesAccess`,
  `spec.security.kubernetesRole`, and `spec.security.externalEgress`.
- Provider Datalab also injects storage and service credentials, persistent
  workspace volumes, and generated namespace-level NetworkPolicies.

This is a useful sandbox baseline, not a complete isolation model. A session
can still do whatever its mounted credentials, Kubernetes role, network access,
volumes, and enabled applications allow. The platform operator owns the outer
guardrails: ingress authentication, RBAC, Pod Security, NetworkPolicy, quotas,
storage policy, backup, retention, and audit.

## Where Enforcement Lives

Provider Datalab expresses workspace intent and renders the Educates resources,
credentials, volumes, and generated NetworkPolicies for a `Datalab`. Educates
runs the workspace runtime and applies its native namespace, token, role,
vcluster, registry, Docker, and session controls.

The platform still enforces the boundary around that runtime. The operator owns
the enforcing CNI, admission policy such as Kyverno, ingress authentication and
authorization, DNS, storage classes, cloud IAM, bucket policy, backup, retention,
audit, and any node isolation for privileged workloads.

## Access to a Datalab

Workspace access can be Keycloak-managed by Provider Datalab or delegated to
the platform ingress layer with `auth.type: delegated`. Delegated mode does not
mean unauthenticated access; it means authentication and authorization are
attached before traffic reaches the workspace runtime.

For Keycloak-backed access, each Datalab gets a confidential OAuth client named
after the Datalab. Provider Datalab publishes the credentials consumers need in
the runtime workshop namespace as `<datalab>-oauth2-client`, with keys
`client_id` and `client_secret`.
Treat the runtime Secret as a workspace machine credential: readers can mint
client-credentials tokens for that Datalab. Human access uses `ws_access` or
`ws_admin`; the generated client service account receives only `ws_api`.

See the [Authentication](../how-to-guides/usage_concepts.md#authentication)
guide for the concrete Keycloak-managed and delegated-ingress patterns,
including NGINX `oauth2-proxy` and APISIX `openid-connect` examples.

## Current Baseline

| Area | Current behavior | Operator check |
| --- | --- | --- |
| Runtime isolation | One Educates runtime namespace per Datalab environment; optional vcluster API for Kubernetes-shaped workflows. | Treat vcluster as API isolation, not stronger Pod isolation. Host namespace policy still matters. |
| Pod security | `spec.security.policy` maps to Educates namespace security policy: `restricted`, `baseline`, or `privileged`. Default is `baseline`. | Decide who may request `privileged`; it enables Docker support. |
| Kubernetes API access | `kubernetesAccess` controls whether a token is mounted. Default is enabled with `kubernetesRole: edit`. | Use stricter environment defaults where workspace code should not call the API. A vcluster changes the API surface; it is not stronger Pod isolation. |
| Network policy | Provider Datalab renders namespace-level egress policies for all runtime Pods. `externalEgress` defaults to `true`; when `false`, only namespace-local Pod egress is allowed by the generated policies. | Verify the CNI enforces NetworkPolicy. Put broad allowed egress CIDRs in `EnvironmentConfig.data.network.externalEgressCIDRs`; put pod/service CIDRs in `podCIDRs` and `serviceCIDR`; put cloud metadata and control-plane CIDRs in `blacklistIPs`; add explicit policies for cross-namespace needs. |
| Ingress auth | `auth.type: delegated` hands authentication to the platform ingress layer. Generated Keycloak clients are confidential and can be reused by direct OIDC ingress integrations through the runtime `<datalab>-oauth2-client` Secret. | Delegated mode is protected only when the operator attaches external auth/authz policy and allows the ingress controller to read the generated runtime Secret. |
| Data access | Object storage, service credentials, PVCs, databases, caches, vector stores, and registry state may be exposed to the session. | Scope credentials and define backup, retention, and deletion behavior outside the session. |

## What Stays Outside

Some controls cannot be solved by Provider Datalab or Kubernetes
NetworkPolicies alone:

- the CNI dataplane must actually enforce NetworkPolicy
- cloud IAM, metadata service settings, bucket policy, backup, retention, and
  audit remain platform responsibilities
- standard NetworkPolicy does not provide ordered deny rules or FQDN-only egress
  allowlists
- privileged workloads need node, runtime, and cloud isolation outside namespace
  policy
- leaked credentials must be rotated and audited; policy does not revoke them

## Operator Contract

For production shared clusters, the operator should be able to answer these questions for engineers, users, and governance reviewers:

- Which data and services can this workspace read or write?
- Is Kubernetes API access disabled, `view`, `edit`, or `admin`?
- Is network egress broad, allowlisted, internal-only, or offline?
- Are Educates and Provider Datalab NetworkPolicies aligned, given that
  Kubernetes NetworkPolicies are additive?
- Are Pod Security, quotas, storage classes, and privileged/Docker use enforced
  by policy instead of convention?
- What persists after the session stops, what is backed up, and who can approve deletion?

## Related Pages

- [Workspace Sessions as Sandboxes](workspace-sessions.md) explains the session
  authority model.
- [Sandbox Security Measures](sandbox-controls.md) describes the current
  NetworkPolicy baseline and the next hardening steps.
