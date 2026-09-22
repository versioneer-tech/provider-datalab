# ADR-001: Use Datalab as the Public Contract

## Status

Accepted

## Date

2026-06-20

## Implementation

Implemented.

Users create a `Datalab`. Provider Datalab turns it into a working data
workspace and reports session information on the same resource.

Educates is the core runtime used by the current implementation. Its resources
are created and managed internally; users and client tools do not need to know
about them.

Educates also provides the browser editor and terminal. Platform ingress can
delegate authentication to Keycloak before a request reaches the Educates
session.

## Context

A data workspace needs many things: an editor, a terminal, persistent files,
credentials, networking, and optional services. Exposing every resource needed
to build that workspace would give users a complicated and fragile API.

We need one stable contract that describes what a user wants, while allowing
the implementation behind it to change.

## Decision

### Make `Datalab` the only public workspace resource

Users and GitOps tools work with the namespaced `Datalab` resource. It describes the desired workspace,
including its named sessions and optional capabilities.

The Datalab name, namespace, and UID form its stable identity. Generated Pod,
Secret, and runtime-resource names are not part of the public contract.

### Use Educates as the internal runtime primitive

Educates provides the editor, terminal, workspace Pod, session runtime, and
optional applications. Crossplane translates a Datalab into the Educates and
Kubernetes resources required to run it.

This translation is an implementation detail:

```text
User or GitOps tool
  -> Datalab
     -> Provider Datalab reconciliation
        -> internal runtime resources
           -> working Datalab session
```

Clients never create, update, discover, or depend on Educates resources
directly. Crossplane owns those generated resources. This keeps one source of
truth and lets the runtime implementation evolve without changing how users
manage a Datalab.

The same rule applies if the internal runtime changes later. Runtime resources
remain projections of the Datalab and do not become a second public workspace
API.

### Keep user choices separate from operator policy

The Datalab spec contains choices that a user is allowed to make. The
operator-owned `EnvironmentConfig` contains platform settings such as ingress,
authentication, storage classes, security defaults, and extension packages.

Crossplane combines both sets of input. Users therefore get a small API, while
operators keep control of security and infrastructure policy.

### Manage sessions through the Datalab

Each session has a unique name and a desired state such as `started` or
`stopped`. Provider Datalab creates the internal runtime for started sessions
and reports the observed phase, message, and browser URL in
`Datalab.status.sessions`.

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
Datalab API stable and avoids baking every tool into one large base image.

## Why This Design

| Design choice | Reason |
| --- | --- |
| One Datalab API | Users have one clear object to create, review, and manage. |
| Educates stays internal | Clients are not coupled to runtime-specific resources or names. |
| Access runtime stays internal | The access implementation can change without creating a second user API. |
| Crossplane owns generated resources | Reconciliation has one owner and does not compete with user changes. |
| User input and operator policy are separate | Self-service does not bypass platform security or infrastructure rules. |
| Status is copied to the Datalab | Clients do not need broad access to internal resources. |
| Credentials stay in Secrets | The public API does not become a credential-delivery channel. |

## Consequences

- Provider Datalab is self-contained: clients need only the Datalab API.
- Educates is essential to the current implementation but is not part of the
  client contract.
- Changing the internal runtime does not require a second public workspace
  model.
- Crossplane remains responsible for generated-resource ownership and cleanup.
- Operators must validate user-selectable Secret references and other
  policy-sensitive options.
- Some lifecycle behavior still needs live transition tests.