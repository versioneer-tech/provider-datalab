# Provider Datalab

Welcome to the **Provider Datalab** documentation.  
This Crossplane provider delivers a unified way to provision cloud workspaces for your data exploration and data processing tasks on Kubernetes.  

It provides a **Datalab Composite Resource Definition (XRD)** and ready-to-use **Compositions** to connect to storage and provision vclusters, identity integration, and supporting services for collaborative analysis.

---

## Features

- **Workspace abstraction**  
  Define and provision full-featured data labs based on Educates or Jupyter as a single resource.  
- **Multi-tenant support**  
  Each Datalab can run isolated inside a Kubernetes namespace or in a dedicated virtual cluster (vcluster).  
- **Integrated identity**  
  Seamless authentication and authorization via Keycloak.  
- **Declarative storage**  
  Provision and attach buckets with access policies.  
- **Extensible by design**  
  Built on Crossplane v2, ready to extend with new resources.  

---

## Installation

To install the configuration package into your Crossplane environment, e.g. based on Educates, use:

```yaml
apiVersion: pkg.crossplane.io/v1
kind: Configuration
metadata:
  name: datalab-educates
spec:
  package: ghcr.io/versioneer-tech/provider-datalab/eductaes<!version!>
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

Access to the datalab is restricted to Alice, since she currently is the only user associated with this lab.  

Combined with a small, cluster-specific `EnvironmentConfig` (realm, ingress domain/class, storage secret), the platform handles the rest—provisioning the chosen runtime, mounting credentials, and preloading content.  


!!! note

    All configuration packages built from `provider-datalab` (educates, jupyter,...) share the same Composite Resource Definition!

### More Examples
Check the [examples folder](https://github.com/versioneer-tech/provider-datalab/tree/main/examples/base) in the GitHub repository for complete scenarios, including:
- Datalabs with multiple users
- Datalabs with integrated storage
- Identity-aware environments