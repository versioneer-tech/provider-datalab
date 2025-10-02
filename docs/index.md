# Provider Datalab

Welcome to the **Provider Datalab** documentation.  
This Crossplane provider delivers a unified way to provision cloud workspaces for your data exploration and data processing tasks on Kubernetes.  

It provides a **Datalab Composite Resource Definition (XRD)** and ready-to-use **Compositions** to provision vclusters, storage, identity integration, and supporting services for collaborative analysis.

---

## Features

- **Workspace abstraction**  
  Define and provision full-featured data labs as a single resource.  
- **Multi-tenant support**  
  Each Datalab can run isolated inside a virtual cluster (vcluster).  
- **Integrated identity**  
  Seamless authentication and authorization via Keycloak.  
- **Declarative storage**  
  Provision and attach buckets with access policies.  
- **Extensible by design**  
  Built on Crossplane v2, ready to extend with new resources.  

---

## Installation

To install the configuration package into your Crossplane environment:

```yaml
apiVersion: pkg.crossplane.io/v1
kind: Configuration
metadata:
  name: datalab
spec:
  package: ghcr.io/versioneer-tech/provider-<educates|jupyter|...>:<x.x>
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
```

Pair it with a small, cluster‑specific `EnvironmentConfig` (realm, ingress domain/class, storage secret) and the platform handles the rest—provisioning the runtime you’ve standardized on, mounting credentials, and preloading content.

### More Examples
Check the [examples folder](https://github.com/versioneer-tech/provider-datalab/tree/main/examples) in the GitHub repository for complete scenarios, including:
- Datalabs with multiple users
- Datalabs with integrated storage
- Identity-aware environments

---

## Concepts

### Sessions

A Datalab may declare one or more `spec.sessions`. Each string value corresponds to a **WorkshopSession** created at runtime.  
If no sessions are given, no runtime will be started. Sessions can be patched into the spec later if needed.

### Files and the Workshop Tab

The `spec.files` array is optional. When empty or omitted, **no workshop tab** is rendered in the Educates UI.  
Providing at least one file source enables the workshop tab and mounts content into the environment.

Supported sources:

- **OCI image** (`spec.files[].image`)  
- **Git repository** (`spec.files[].git`)  
- **HTTP(S) download** (`spec.files[].http`)  

Filters (`includePaths`, `excludePaths`, `newRootPath`, `path`) control what ends up visible.

### vcluster toggle

`spec.vcluster` is a boolean flag.  
- `true` → the datalab provisions a vcluster for runtime isolation.  
- `false` → workloads run directly in the namespace.

### Storage Secret

The Datalab requires credentials to a S3 compatible storage system. This Secret must reside in the namespace specified by `storage.secretNamespace` and include at least the `access_key` and `access_secret`, with endpoint and provider listed in `EnvironmentConfig.data.storage`.  


---

## Links

- [API Reference](http://provider-datalab.versioneer.at/latest/reference-guides/api/)  
- [Examples](https://github.com/versioneer-tech/provider-datalab/tree/main/examples) 

---

!!! note

    All configuration packages built from `provider-storage` share the same Composite Resource Definition!