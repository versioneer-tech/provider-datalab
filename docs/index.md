# Welcome to Provider Datalab

**Provider Datalab is a PaaS-style building block for shared data and compute
environments.** It provides a Crossplane API that lets teams request the
resources they need through one `Datalab` claim, while platform operators keep
control of policy, capacity, and lifecycle.

A Datalab gives a team tools to browse, share, and work with object-storage
data. The storage itself can be provisioned through
[Provider Storage](https://provider-storage.versioneer.at/) or another storage
service. Provider Datalab uses the resulting endpoint and credentials; it does
not create buckets.

The same claim can request managed services, including PostgreSQL databases,
MongoDB document stores, Redis caches, Qdrant vector databases, and a Docker
registry. These services remain visible to the platform team, which can manage
their security, backup, capacity, and lifecycle.

Compute is optional. A named Datalab session provides a hosted VS Code
instance, a terminal, a persistent workspace, and common command-line tools.
It is preconfigured to use the approved object storage. When Kubernetes access
is allowed, users can deploy workloads and supporting components to their
assigned namespace or to an optional vCluster with a separate Kubernetes API.

These docs are written mainly for platform operators. Operators define the
available services and control identity, ingress, RBAC, Pod Security,
NetworkPolicies, quotas, network access, backups, and lifecycle. Engineers and
data users can use the examples to understand what a `Datalab` request creates
and which responsibilities remain with the platform team.

## Architecture

The current Educates runtime provides the Datalab browser editor and terminal.
Platform ingress can protect it through delegated Keycloak authentication.
[ADR-001](architecture/0001-use-the-datalab-crd-as-the-workspace-contract.md)
defines the `Datalab` resource as the public contract and keeps runtime
resources as internal implementation details.

Provider Datalab requires [Crossplane v2 or later](https://crossplane.io). It provides a tenant-facing `Datalab` API and compositions that connect systems you already operate: Kubernetes namespaces, ingress, identity, object-storage credentials, persistent volumes, database operators, cache and vector-store operators, and the Educates runtime.

## Operator Contract

For an operator, a `Datalab` is not just a notebook or a pod. It is the contract for a tenant-facing service:

- You define the platform boundary in `EnvironmentConfig`: ingress, authentication, storage endpoint, quotas, security defaults, and optional backend services.
- A tenant, GitOps process, or higher-level API submits a `Datalab` claim describing users, sessions, files, storage credentials, runtime permissions, and requested data services.
- Crossplane compositions create or configure the required Kubernetes, identity, storage access, and backend resources.
- The resulting resources stay visible to the operator, so lifecycle, policy, capacity, and backup responsibility are clear.

This is the main design point: Provider Datalab makes self-service smooth
without hiding state from the platform team. In the current API, a named
session is a long-lived environment, while its workspace Pod is replaceable.
The Pod provides the browser editor, terminal, tools, and preconfigured session
access. Large, isolated, or repeatable work belongs on separate task workloads.
Its `/home/eduk8s` workspace is backed by the session's stable PVC; persistence
of other session applications is not yet proven. Databases, buckets, persistent
volumes, and other stateful services remain platform concerns.

For governance, this gives sponsors a concrete review surface: a Datalab can be approved, costed, secured, and retired as a named platform service instead of becoming unmanaged compute plus scattered credentials.

## What It Provides

Provider Datalab provides:

- A **Datalab Composite Resource Definition (XRD)**.
- **Compositions for Crossplane v2 or later** that create environments with sessions, storage access, vClusters, identity wiring, and optional managed backends.
- A default `datalab-educates` runtime that launches **VS Code Server**,
  terminals, and common tools such as `awscli` and `rclone`, with a shared
  `package-r` Data service.
- Optional **Keycloak-managed access**, including confidential clients, runtime OAuth2 credential Secrets, groups, roles, role scope mappings, role bindings, service-account API access, and memberships.
- Support for delegated authentication through the surrounding platform, for example NGINX external auth or APISIX OIDC protection at the ingress layer.
- Optional platform-managed services from the same `Datalab` claim: PostgreSQL databases, MongoDB document stores, Redis key-value/cache stores, Qdrant vector stores, and a Docker registry.

Users get an online IDE with configured storage, credentials, and managed
services. Software engineers get a declarative platform contract that they can
review.

---

## Features

- **PaaS-style service abstraction**
  Offer online IDEs, storage access, databases, caches, vector stores, and registries through one Kubernetes resource.
- **Operator-visible provisioning**
  Keep generated resources inspectable and governable instead of burying durable state inside user sessions.
- **Multi-tenant runtime isolation**
  Run each Datalab inside a namespace or, where useful, with a dedicated virtual Kubernetes control plane (vCluster).
- **Integrated or delegated identity**
  Use Keycloak-managed workspace access where appropriate, or set `auth.type: delegated` and delegate authentication to the ingress layer. Generated Datalab clients are confidential, include a service-account-only `ws_api` role for automation, and can add configured service audiences to access tokens.
- **Storage integration**
  Consume object-storage credentials from Provider Storage or another storage
  process, and make them available to session tools and the shared Data service.
- **Additional services**
  Connect other operator-owned services without changing the user-facing API.

---

## Installation

To install the configuration package into your Crossplane environment, e.g. based on Educates, use:

```yaml
apiVersion: pkg.crossplane.io/v1
kind: Configuration
metadata:
  name: datalab-educates
spec:
  package: ghcr.io/versioneer-tech/provider-datalab/educates<!version!>
  skipDependencyResolution: true
```

---

## Quickstart

### Minimal Example

```yaml
apiVersion: pkg.internal/v1beta2
kind: Datalab
metadata:
  name: team-wonderland
spec:
  users:
  - alice
  sessions:
  - name: default
  vcluster: true
```

This provisions a vCluster in a dedicated Kubernetes namespace and starts VS
Code Server, a terminal, and the bundled tools. The declared session gets a
workspace PVC that remains available when the session is stopped. Its Data tab
uses the shared `package-r` service to access S3.

Access to the datalab is intended for Alice, since she currently is the only user associated with this lab. Depending on the platform configuration, access can be enforced by Keycloak-managed resources or by delegated ingress authentication.

The cluster-specific `EnvironmentConfig` defines the realm, ingress, and
storage settings. The provider then creates the runtime, supplies credentials,
and loads the requested content.

The ingress controller is selected by `ingress.class`.

The same claim can also request stateful platform services:

```yaml
spec:
  databases:
    pg0:
      names:
      - analytics
      storage: 1Gi
      backupStorage: 3Gi
  documentStores:
    prod:
      storage: 1Gi
  cacheStores:
    prod:
      storage: 1Gi
  vectorStores:
    prod:
      storage: 1Gi
  registry:
    enabled: true
    storage: 3Gi
```

Those resources are provisioned through the platform's installed operators and stay visible as managed infrastructure. That is what lets the operator decide how they are backed up, monitored, upgraded, and retired.

!!! note

    The `datalab-educates` configuration package uses the shared `Datalab` Composite Resource Definition.

### More Examples

Check the [examples folder](https://github.com/versioneer-tech/provider-datalab/tree/main/examples/base) in the GitHub repository for complete scenarios, including:

- Datalabs with multiple users
- Datalabs with integrated storage
- Identity-aware environments
- Datalabs with managed databases, document stores, cache stores, vector stores, and registries
