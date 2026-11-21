# ADR-001: Use Datalab as the Public Contract

> Written: 02.12.2025. Revised: 21.11.2026.

## Status

Accepted.

Users create a `Datalab` to declare team members, services, virtual clusters,
and session storage. Workloads use the virtual Kubernetes API. Each virtual
cluster includes Agent Sandbox CRDs, its controller, and a sandboxd template.

## Context

A data workspace needs persistent files, credentials, networking, and optional
services. Exposing every host resource needed for that workspace would give
users a complicated and fragile API.

We need one stable contract for team resources and platform policy. Users also
need a Kubernetes API to run and replace their own workloads.

## Decision

### Use Datalab for team resources

Users and GitOps tools work with the namespaced `versioneer.at/v1` Datalab.
It describes team membership, named virtual clusters, managed services, and
session PVCs.

The Datalab name, namespace, and UID form its identity. The composition creates
a host service namespace with the Datalab name. Its quota, LimitRange, and
network policies apply to the team's services and virtual workloads.

The Datalab is the network boundary. Host policies restrict traffic between
Datalabs and permit shared networking within one Datalab, including across its
virtual clusters. A virtual cluster is an API boundary, not a separate network
boundary. Router authorization controls routed requests; it does not isolate
workloads within a Datalab.

### Keep generated host resources under provider control

Crossplane owns the generated namespaces, service resources, identity settings,
and virtual cluster configuration. Users manage their application workloads
through a virtual Kubernetes API:

```text
User or GitOps tool
  -> Datalab
     -> Provider Datalab reconciliation
        -> host service namespace and managed services
        -> virtual Kubernetes clusters and session PVCs

User or workload client
  -> virtual Kubernetes API
     -> Sandbox controller
        -> sandboxd Pod that mounts a session PVC
```

### Keep user choices separate from operator policy

The Datalab spec contains choices that a user is allowed to make. The
operator-owned EnvironmentConfig contains platform settings such as ingress,
Keycloak realm, storage classes, security defaults, and runtime images.

Crossplane combines both sets of input to create the team resources.

### Keep session storage independent of workloads

Each session has a unique name, virtual cluster, namespace, and optional PVC
size. Provider Datalab creates its PVC and reports the location in
`status.sessions`. The session entry does not start a workload.

An external client or orchestration service creates the named Session Sandbox
on first use. It mounts the existing PVC at `/workspace` and does not use
`volumeClaimTemplates` to create another session PVC. The external service
checks ownership and the PVC binding before it reuses a Sandbox.

The external service starts and suspends the Sandbox through its native
`spec.operatingMode`. Crossplane does not own the Sandbox CR or reset its mode.
The Agent Sandbox controller stays inside the virtual cluster and manages the
workload Pod and optional Service. The external service reads readiness and
operating mode from the Sandbox CR. `status.sessions` reports PVC references
only.

Do not add `operatingMode`, `running`, `suspended`, or equivalent per-Sandbox
runtime fields to Datalab, including `spec.sessions`. The existing
`spec.vclusters.<instance>.hibernated` controls the whole virtual cluster.
Hibernation must preserve Sandbox CRs, their operating modes, and session PVCs.
After resume, Running Sandboxes can start again; Suspended Sandboxes must stay
suspended.

Pod replacement and Sandbox deletion keep the session PVC. An external client
can recreate a deleted Sandbox with the same PVC. Removing the session entry
deletes the PVC, so clients must stop workloads that use it first.

### Keep task execution under external control

The external orchestration service creates and removes temporary SandboxClaims.
Claims use `warmPoolRef` to select an approved SandboxWarmPool, which references
an approved SandboxTemplate. Provision the pool with `replicas: 0` so it does
not keep spare workloads running. Each task uses separate temporary storage
and must not mount a persistent session PVC.

Keep orchestration, cleanup, file transfer, and Kubernetes credentials outside
Session and Task Sandboxes. A Session Sandbox must not orchestrate Task
Sandboxes. Task definitions do not belong in `spec.sessions`.

### Use Kubernetes port-forwarding and RBAC

Clients connect through the virtual Kubernetes API and use Kubernetes RBAC.
They port-forward directly to the Sandbox Pod for sandboxd HTTP and gRPC, or
for application TCP ports in that Pod. A per-Sandbox Service is not required.
Grant Pod read access and `pods/portforward` access in the required namespace.
RBAC controls access to the Pod subresource, not individual port numbers.
The provider supplies the zero-replica task pool; it does not create task
Claims or session workload Pods.

Do not deploy Sandbox Router or a Sandbox-specific oauth2-proxy. Do not add
router capabilities, sandboxd tokens, or routing fields to Datalab for this
model. Keycloak continues to authenticate callers to the virtual API; virtual
Kubernetes RBAC authorizes their operations. See
[ADR-003](0003-token-exchange-for-downscoping.md#use-the-virtual-api-for-sandbox-access).

RBAC does not authenticate direct Pod traffic. The default template does not
enable sandboxd token authentication. Workloads within the same Datalab can
reach its HTTP and gRPC listeners over the shared network.

Port-forward connections end when their Pod stops or is replaced. Clients must
discover the current Pod and reconnect after resume or replacement. Keep Pod
discovery separate from sandboxd calls so a later routing transport can use the
same Sandbox identity and PVC without changing storage ownership.

Sandbox Router, direct authenticated routes, scoped tokens, and browser routing
are deferred. No public session URL or per-session access list is added to
Datalab. Shared networking within a Datalab remains unchanged.

### Keep credentials out of the API

Credentials are read from referenced Kubernetes Secrets and copied only where
they are needed. Secret values never belong in the Datalab spec, status, logs,
or normal client output. Status reports connection Secret references.

Membership and host network rules apply to the whole Datalab. Use separate
Datalabs when workloads need different membership or trust boundaries.

### Add tools through the runtime image

Operators can select a compatible sandboxd image with additional tools in
EnvironmentConfig. Commands execute in that container. This keeps tool choices
out of the Datalab API.

## Consequences

- Datalab provides one resource for team membership, services, and storage.
- Clients use the virtual Kubernetes API to manage workloads.
- Crossplane owns generated host resources and their cleanup.
- Session storage can outlive a Sandbox and its Pod.
- External services own Sandbox operating modes and task orchestration.
- Workloads within one Datalab share its network; separate Datalabs provide
  separate team boundaries.
- Operators must validate Secret references and other policy-sensitive options.
- Render tests check generated resources; live tests check workload APIs,
  persistence, authorization, and service access.
