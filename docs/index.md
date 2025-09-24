# Cloud Data Labs, by Design

**Datalab** is a Crossplane‑powered abstraction that turns “data workspace” provisioning into a clean, versioned API. It applies a platform‑engineering mindset: productize the golden path, hide the boilerplate, and let teams request a lab with a single spec—while your platform composes identity, ingress, storage, and content bootstrapping under the hood.

- **Stable API, many runtimes.** The same `Datalab` spec can back different open‑source experiences such as **Educates** or **Jupyter**—your platform decides, users don’t have to.
- **GitOps‑first.** Everything is declarative and reviewable: labs, policies, and updates flow through your existing CI/CD.
- **Batteries included.** Built‑in file bundling (OCI image, Git, HTTP) seeds each lab with ready‑to‑run materials.
- **Portable & multi‑tenant.** Any Kubernetes, any ingress class, namespaced isolation by default.
- **Upgrade by bump.** Ship improvements safely via package version bumps; rollback with revision history.

## How it feels

```yaml
apiVersion: pkg.internal/v1beta1
kind: Datalab
metadata:
  name: demo
  namespace: datalab
spec:
  users:
  - alice
  sessions:
  - default
  files:
  - git:
      url: https://github.com/demo/datalab-assets
      ref: origin/main
    includePaths: ["/**"]
```

Pair it with a small, cluster‑specific `EnvironmentConfig` (realm, ingress domain/class, storage secret) and the platform handles the rest—provisioning the runtime you’ve standardized on, mounting credentials, and preloading content.

## Sessions

A Datalab may declare one or more `spec.sessions`. Each string value corresponds to a **WorkshopSession** created at runtime.  
If no sessions are given, no runtime will be started. Sessions can be patched into the spec later if needed.

## Files and the Workshop Tab

The `spec.files` array is optional. When empty or omitted, **no workshop tab** is rendered in the Educates UI.  
Providing at least one file source enables the workshop tab and mounts content into the environment.

Supported sources:

- **OCI image** (`spec.files[].image`)  
- **Git repository** (`spec.files[].git`)  
- **HTTP(S) download** (`spec.files[].http`)  

Filters (`includePaths`, `excludePaths`, `newRootPath`, `path`) control what ends up visible.

## vcluster toggle

`spec.vcluster` is a boolean flag.  
- `true` → the datalab provisions a vcluster for runtime isolation.  
- `false` → workloads run directly in the namespace.

## Storage

The `storage` section in the `EnvironmentConfig` references a Kubernetes Secret — named identically to the Datalab — which must already exist in the cluster.  
This Secret must reside in the namespace specified by `storage.secretNamespace` and include at least:

- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`

The values must provide access to the endpoint and provider listed in `EnvironmentConfig.data.storage`.  
You may create this secret manually before applying the Datalab.

## API Reference

For the full published XRD with all fields, see the [API Reference Guide](https://provider-datalab.versioneer.at/latest/reference-guides/api/).
