# ADR-001: Use Datalab as the Public Contract

> Written: 02.12.2025. Revised: 03.11.2026.

## Status

Accepted

## Implementation

Implemented.

Users create a `Datalab`. Provider Datalab turns it into a working data
workspace and reports session information on the same resource.

Educates is the first implementation of runtime sessions. It provides the
browser editor and terminal. Its resources are created and managed internally.

## Context

A data workspace needs many things: an editor, a terminal, persistent files,
credentials, networking, and optional services. Exposing every resource needed
to build that workspace would give users a complicated and fragile API.

We need one stable contract that describes what a user wants, while allowing
the implementation behind it to change.

## Decision

### Make `Datalab` the only public workspace resource

Users and GitOps tools work with the namespaced `Datalab` resource. It describes
the desired workspace, including its named sessions and optional capabilities.

The Datalab name, namespace, and UID form its stable identity. Generated Pod,
Secret, and runtime-resource names are not part of the public contract.

### Keep the runtime implementation internal

The internal runtime provides the editor, terminal, workspace Pod, sessions,
and optional applications. Crossplane translates a Datalab into the runtime
and Kubernetes resources required to run it.

This translation is an implementation detail:

```text
User or GitOps tool
  -> Datalab
     -> Provider Datalab reconciliation
        -> internal runtime resources
           -> working Datalab session
```

Clients never create, update, discover, or depend on runtime resources
directly. Crossplane owns those generated resources. This keeps one source of
truth and lets the runtime implementation evolve without changing how users
manage a Datalab.

The same rule applies if the internal runtime changes later. Runtime resources
remain projections of the Datalab and do not become a second public workspace
API.

### Keep user choices separate from operator policy

The Datalab spec contains choices that a user is allowed to make. The
operator-owned `EnvironmentConfig` contains platform settings such as ingress,
Keycloak realm, storage classes, security defaults, and extension packages.

Crossplane combines both sets of input. Users therefore get a small API, while
operators keep control of security and infrastructure policy.

### Manage sessions through the Datalab

Each session has a unique name and a desired state such as `started` or
`stopped`. Provider Datalab creates the internal runtime for started sessions
and reports the observed phase, message, and browser URL in
`Datalab.status.sessions`. A stopped session keeps its workspace PVC.

Clients read the Datalab status. They do not look up the internal runtime.
Diagnostic phase and message text is not a stable machine-readable lifecycle
API; richer clients will need typed status fields.

The current API does not have a separate environment or profile object. Add
such concepts only through a separate decision and a compatible API change.

### Keep credentials out of the API

Credentials are read from referenced Kubernetes Secrets and copied only where
the runtime needs them. Secret values never belong in the Datalab spec, status,
logs, or normal client output.

Credentials and security settings currently apply to the whole Datalab. Use
separate Datalabs when workloads need separate Kubernetes control planes or a
stronger trust boundary.

### Add tools without changing the contract

Operators can add runtime tools through extension packages. This keeps the
Datalab API stable and avoids putting every tool in one large base image.

## Why This Design

| Design choice | Reason |
| --- | --- |
| One Datalab API | Users have one clear object to create, review, and manage. |
| Runtime stays internal | Clients are not coupled to runtime-specific resources or names. |
| Crossplane owns generated resources | Reconciliation has one owner and does not compete with user changes. |
| User input and operator policy are separate | Self-service does not bypass platform security or infrastructure rules. |
| Status is copied to the Datalab | Clients do not need broad access to internal resources. |
| Credentials stay in Secrets | The public API does not become a credential-delivery channel. |

## Consequences

- Provider Datalab is self-contained: clients need only the Datalab API.
- Changing the internal runtime does not require a second public workspace
  model.
- Crossplane remains responsible for generated-resource ownership and cleanup.
- Operators must validate user-selectable Secret references and other
  policy-sensitive options.
- Render tests check generated resources; live tests must also check session
  transitions and access to services.
