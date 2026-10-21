# Welcome to Provider Datalab

**Provider Datalab creates shared data and compute environments.**
It provides a Crossplane API that lets teams request the
resources they need through one `Datalab` claim, while platform operators keep
control of policy, capacity, and lifecycle.

A Datalab gives a team tools to browse, share, and work with object-storage
data. The storage itself can be provisioned through
[Provider Storage](https://provider-storage.versioneer.at/) or another storage
service. Provider Datalab uses the resulting endpoint and credentials; it does
not create buckets.

To share data with the world, put it in your Datalab's `public` folder and
send the public link. Readers can browse and download the files without an
account. See [Sharing Data with the World](how-to-guides/usage_concepts.md#sharing-data-with-the-world).

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
[ADR-001](architecture/0001-use-the-datalab-crd-as-the-workspace-contract.md)
defines the `Datalab` resource as the public contract and keeps runtime
resources as internal implementation details.

Provider Datalab requires [Crossplane v2 or later](https://crossplane.io). It provides a tenant-facing `Datalab` API and compositions that connect systems you already operate: Kubernetes namespaces, ingress, identity, object-storage credentials, persistent volumes, database operators, cache and vector-store operators, and the Educates runtime.

## How It Works

Each Datalab starts with a request and uses the platform's shared settings:

- The operator defines shared settings in `EnvironmentConfig`: ingress, Keycloak realm, storage endpoint, quotas, security defaults, and optional backend services.
- A tenant, GitOps process, or higher-level API submits a `Datalab` claim describing users, sessions, files, storage credentials, runtime permissions, and requested data services.
- Crossplane compositions create or configure the required Kubernetes, identity, storage access, and backend resources.
- The operator can inspect the created resources and manage their capacity, access, and backups.

Each named session stores its `/home/eduk8s` workspace on a stable PVC. Its
workspace Pod provides the browser editor, terminal, and tools, and can be
replaced. Use separate task workloads for large jobs or work that needs its
own resources. Persistence of other session applications still needs testing.
The platform team manages storage, databases, and their backups.

## What It Provides

Provider Datalab provides:

- A **Datalab Composite Resource Definition (XRD)**.
- **Compositions for Crossplane v2 or later** that create environments with sessions, storage access, vClusters, identity wiring, and optional managed backends.
- A default `datalab-educates` runtime that launches **VS Code Server**,
  terminals, and common tools such as `awscli` and `rclone`, with a shared
  `package-r` Data service.
- **Keycloak resources for each Datalab**, including confidential clients, runtime OAuth2 credential Secrets, groups, roles, role scope mappings, role bindings, service-account API access, and memberships.
- Optional platform-managed services from the same `Datalab` claim: PostgreSQL databases, MongoDB document stores, Redis key-value/cache stores, Qdrant vector stores, and a Docker registry.

Users get an online IDE with configured storage, credentials, and managed
services. Engineers can review the configuration in the `Datalab` spec.

---

## Features

- **One API for workspace services**
  Offer online IDEs, storage access, databases, caches, vector stores, and registries through one Kubernetes resource.
- **Resources operators can inspect**
  Review the resources created for each Datalab and configure their backups and access rules.
- **Multi-tenant runtime isolation**
  Run each Datalab inside a namespace or, where useful, with a dedicated virtual Kubernetes control plane (vCluster).
- **Datalab identity**
  Generated Datalab clients are confidential, include a service-account-only `ws_api` role for automation, and can add configured service audiences to access tokens.
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

Access to the datalab is intended for Alice, since she currently is the only user associated with this lab. Provider Datalab creates the Keycloak groups, memberships, and roles that the platform can use for authorization.

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

The platform's installed operators create these resources. Configure backups, monitoring, upgrades, and deletion for each service you offer.

!!! note

    The `datalab-educates` configuration package uses the shared `Datalab` Composite Resource Definition.

### More Examples

Check the [examples folder](https://github.com/versioneer-tech/provider-datalab/tree/main/examples/base) in the GitHub repository for complete scenarios, including:

- Datalabs with multiple users
- Datalabs with integrated storage
- Identity-aware environments
- Datalabs with managed databases, document stores, cache stores, vector stores, and registries
