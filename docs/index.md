# Welcome to Provider Datalab

The **Provider Datalab** package turns Kubernetes into a platform for collaborative, cloud-native workspaces, built on [Crossplane v2](https://crossplane.io). It gives **end users** self-service access to reproducible environments for coding, data exploration, and analysis — and it gives **operators** a unified control plane to provision and secure those environments at scale.

Instead of hand-crafting Jupyter or Educates deployments, every workspace is declared through a single Kubernetes Custom Resource: the `Datalab` claim. This claim captures who should have access, whether a virtual cluster is needed, what sessions should run, and what files or datasets should be preloaded — while Crossplane v2 and the compositions take care of provisioning all the moving parts.

For **end users**, this means:

- Launch personal or shared analysis environments with one manifest.  
- Get preconfigured access to storage, credentials, and workshop material.  
- Work inside familiar tools like **VS Code Server, JupyterLab, or terminals**, bundled with utilities such as `awscli` and `rclone`.  

For **operators**, this means:

- A consistent, declarative model for managing heterogeneous runtime stacks.  
- Automated provisioning of vclusters, identity integration via Keycloak, and storage connections.  
- Extensibility to plug in additional runtimes or policies without changing the user-facing API.  

At its core, Provider Datalab provides:
- A **Datalab Composite Resource Definition (XRD)**  
- **Compositions** powered by **Crossplane v2** to provision environments with storage, sessions, vclusters, and identity wiring  
- Seamless integration of authentication and access control  

With Provider Datalab, workspaces become **declarative, multi-tenant, and self-service**, while operators retain full control over identity, security, and resource governance.


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