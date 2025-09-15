# Cloud Data Labs, by Design

**Datalab** is a Crossplane‑powered abstraction that turns “data workspace” provisioning into a clean, versioned API. It applies a platform‑engineering mindset: productize the golden path, hide the boilerplate, and let teams request a lab with a single spec—while your platform composes identity, ingress, storage, and content bootstrapping under the hood.

- **Stable API, many runtimes.** The same `Datalab` spec can back different open‑source experiences such as **Educates** or **Jupyter**—your platform decides, users don’t have to.
- **GitOps‑first.** Everything is declarative and reviewable: labs, policies, and updates flow through your existing CI/CD.
- **Batteries included.** Built‑in file bundling (OCI image, Git, HTTP) seeds each lab with ready‑to‑run materials; S3‑compatible credentials are wired via a simple Secret.
- **Portable & multi‑tenant.** Any Kubernetes, any ingress class, namespaced isolation by default.
- **Upgrade by bump.** Ship improvements safely via package version bumps; rollback with revision history.

## How it feels

```yaml
apiVersion: pkg.internal/v1beta1
kind: Datalab
metadata:
  name: demo
  namespace: demo
spec:
  owner: alice
  members: [bob, carol]
  files:
  - git:
      url: https://github.com/acme/lab-assets
      ref: origin/main
    includePaths: ["/**"]
```

Pair it with a small, cluster‑specific `EnvironmentConfig` (realm, ingress domain/class, storage secret) and the platform handles the rest—provisioning the runtime you’ve standardized on, mounting credentials, and preloading content.
