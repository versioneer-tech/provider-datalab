# ADR-001: Use Datalab as the Public Contract

> Written: 02.12.2025. Revised: 09.11.2026.

## Status

Accepted.

## Implementation

Implemented.

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

Crossplane combines both sets of input. Users get a small API, while operators
keep control of security and infrastructure policy.

### Keep session storage independent of workloads

Each session has a unique name, virtual cluster, namespace, and optional PVC
size. Provider Datalab creates its PVC and reports the location in
`status.sessions`. The session entry does not start a workload.

Clients create a Sandbox that mounts the session PVC. Sandbox replacement
keeps its files. Removing the session entry deletes the PVC, so clients must
stop workloads that use it first. Access uses Kubernetes port-forwarding;
public session URLs are not provided.

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
- Operators must validate Secret references and other policy-sensitive options.
- Render tests check generated resources; live tests check workload APIs,
  persistence, authorization, and service access.
