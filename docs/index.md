# Welcome to Provider Datalab

**Provider Datalab is a PaaS-style building block for platform operators:** it turns one `Datalab` claim into an end-user workspace with an online IDE, object-storage access, managed databases, document stores, key-value/cache stores, vector databases, and an optional Docker registry. Users get a smooth workspace. Operators keep visibility into what was provisioned, so they can own access, capacity, lifecycle, and backups.

Provider Datalab is built on [Crossplane v2](https://crossplane.io). It provides a tenant-facing `Datalab` API and compositions that connect systems you already operate: Kubernetes namespaces, ingress, identity, object-storage credentials, persistent volumes, database operators, cache and vector-store operators, and the Educates runtime.

Provider Datalab does **not** create object-storage buckets. Use [Provider Storage](https://provider-storage.versioneer.at/) or another storage process to create buckets and credentials. Provider Datalab consumes those credentials and wires storage access into the lab.

## Operator Contract

For an operator, a `Datalab` is not just a notebook or a pod. It is the contract for a tenant-facing service:

- You define the platform boundary in `EnvironmentConfig`: ingress, authentication, storage endpoint, quotas, security defaults, and optional backend services.
- A tenant, GitOps process, or higher-level API submits a `Datalab` claim describing users, sessions, files, storage credentials, runtime permissions, and requested data services.
- Crossplane compositions create or configure the required Kubernetes, identity, storage access, and backend resources.
- The resulting resources stay visible to the operator, so lifecycle, policy, capacity, and backup responsibility are clear.

This is the main design point: Provider Datalab makes self-service smooth without hiding state from the platform team. Sessions can be disposable. Databases, buckets, persistent volumes, and other stateful services remain platform concerns.

## What It Provides

At its core, Provider Datalab provides:

- A **Datalab Composite Resource Definition (XRD)**.
- **Crossplane v2 compositions** for creating environments with sessions, storage access, vclusters, identity wiring, and optional managed backends.
- A default `datalab-educates` runtime that launches **VS Code Server**, terminals, a storage browser, and common tools such as `awscli` and `rclone`.
- Optional **Keycloak-managed access**, including clients, groups, roles, role bindings, and memberships.
- Support for delegated authentication through the surrounding platform, for example an ingress controller protected by `oauth2-proxy`.
- Optional platform-managed services from the same `Datalab` claim: PostgreSQL databases, MongoDB document stores, Redis key-value/cache stores, Qdrant vector stores, and a Docker registry.

For end users, this means a simple workspace experience: they can open a familiar online IDE, access storage and credentials that have already been wired in, and work with higher-level services without understanding every underlying Kubernetes resource.


---

## Features

- **PaaS-style service abstraction**
  Offer online IDEs, storage access, databases, caches, vector stores, and registries through one Kubernetes resource.
- **Operator-visible provisioning**
  Keep generated resources inspectable and governable instead of burying durable state inside user sessions.
- **Multi-tenant runtime isolation**
  Run each Datalab inside a namespace or, where useful, inside a dedicated virtual cluster (vcluster).
- **Integrated or delegated identity**
  Use Keycloak-managed workspace access where appropriate, or keep runtime auth disabled and delegate authentication to the platform ingress layer.
- **Storage integration**
  Consume object-storage credentials from Provider Storage or another storage process, and mount them into the lab.
- **Extensible by design**
  Built on Crossplane, ready to connect additional operator-owned services without changing the user-facing API.

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
apiVersion: pkg.internal/v1beta1
kind: Datalab
metadata:
  name: team-wonderland
spec:
  users:
  - alice
  sessions:
  - default
  vcluster: true
```

This provisions a vcluster within a dedicated Kubernetes namespace and starts the Educates tooling stack (including VS Code Server and a terminal), together with bundled utilities. A storage browser is available with storage automatically mounted, and additional tools such as `awscli` and `rclone` are preinstalled to support typical data lab tasks like coding, data exploration, and wrangling.

Access to the datalab is intended for Alice, since she currently is the only user associated with this lab. Depending on the platform configuration, access can be enforced by Keycloak-managed resources or by delegated ingress authentication.

Combined with a small, cluster-specific `EnvironmentConfig` (realm, ingress domain/class, storage secret), the platform handles the rest—provisioning the chosen runtime, mounting credentials, and preloading content.

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
