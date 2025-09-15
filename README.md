# Datalab Provider

This package provides the **Datalab** Composite Resource Definition (XRD) and ready‑to‑use Crossplane v2 Compositions to provision a datalab for multiple runtimes. A Datalab models:
- **Ownership** (`spec.owner`)
- **Membership** (`spec.members[]`)
- **File bundles** (`spec.files[]`) fetched from remote sources and copied into the runtime environment

## Runtimes

Datalab supports multiple runtimes so teams can choose what fits best:

- **Educates** (from [educates.dev](https://educates.dev)) — VS Code Server–based, multi-tenant workspaces that run either in a Kubernetes namespace or inside a vcluster (vcluster optional).
- **Jupyter** — notebook-centric environments running in a Kubernetes namespace *(coming soon)*.

For full documentation, see the project’s [Read the Docs](https://provider-datalab.versioneer.at/) page.

## Install the Configuration Package

Install the package while managing providers and functions separately (e.g., via your GitOps process).

```yaml
apiVersion: pkg.crossplane.io/v1
kind: Configuration
metadata:
  name: datalab
spec:
  package: ghcr.io/versioneer-tech/provider-datalab/educates:<!version!>
  skipDependencyResolution: true
```
> Replace `<!version!>` with the desired release tag.

## Environment configuration (latest)

Supply cluster‑specific settings with an **EnvironmentConfig** (cluster‑scoped). The Datalab Composition reads this via the `prepare-environment` step.

```yaml
apiVersion: apiextensions.crossplane.io/v1beta1
kind: EnvironmentConfig
metadata:
  name: datalab
data:
  iam:
    realm: acme
  ingress:
    class: nginx
    domain: lab.acme.com
    secret: wildcard-tls
  session:
    suffix: s001
  storage:
    secretName: s3-credentials
    secretNamespace: datalab
```

### Field semantics

- `iam.realm` – Identity realm used by Keycloak resources for this Datalab.
- `ingress.class` – IngressClass for routes rendered by the runtime.
- `ingress.domain` – Base DNS domain for generated hostnames.
- `ingress.secret` – TLS secret (certificate) for HTTPS.
- `session.suffix` – Optional suffix to disambiguate session names (e.g., *s001*).
- `storage.secretName` – **Name** of the Secret containing S3‑compatible credentials.
- `storage.secretNamespace` – **Namespace** where that Secret lives.

## Wiring storage credentials

Workloads read storage credentials from a Kubernetes Secret. The default mapping expects these keys:

- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `AWS_REGION`
- `AWS_ENDPOINT_URL`
- (usually) `AWS_S3_FORCE_PATH_STYLE` set to `"true"` for path‑style endpoints

Create the Secret named **`s3-credentials`** in the target (e.g. **`datalab`**) namespace:

```bash
kubectl -n datalab create secret generic s3-credentials   --from-literal=AWS_ACCESS_KEY_ID=<KEY_ID>   --from-literal=AWS_SECRET_ACCESS_KEY=<SECRET>   --from-literal=AWS_REGION=<REGION>   --from-literal=AWS_ENDPOINT_URL=<https://s3.example.com>   --from-literal=AWS_S3_FORCE_PATH_STYLE=true
```

Ensure your `EnvironmentConfig.data.storage` points at this Secret via `secretName` and `secretNamespace` as shown above.

## Datalab spec

### Minimal example

```yaml
apiVersion: pkg.internal/v1beta1
kind: Datalab
metadata:
  name: acme
  namespace: datalab
spec:
  owner: alice
```

### With members and file bundles

```yaml
apiVersion: pkg.internal/v1beta1
kind: Datalab
metadata:
  name: acme
  namespace: datalab
spec:
  owner: alice
  members: [bob, eric]

  files:
  - image:
      url: ghcr.io/acme/lab-assets:2025.09
    includePaths:
    - /data/**
    - /README.md
    path: .

  - git:
      url: https://github.com/acme/lab-assets
      ref: origin/main
    newRootPath: /data
    includePaths: ["/**"]

  - http:
    url: https://downloads.acme.example.com/data.tar.gz
    includePaths: ["/**"]
    path: ./data
```

**`spec.files[]` sources**

- **`image`**: pull files from an OCI image  
  Options: `url` (required), `secretRef`, `dangerousSkipTLSVerify`, `tagSelection.semver`
- **`git`**: clone content from a Git repository  
  Options: `url`, `ref` (required), `refSelection.semver`, `lfsSkipSmudge`, `verification.publicKeysSecretRef`, `secretRef`
- **`http`**: download file/archive over HTTP(S)  
  Options: `url` (required), `sha256`, `secretRef`

Common filters/destination: `includePaths`, `excludePaths`, `newRootPath`, `path`.

## License

Apache 2.0 (Apache License Version 2.0, January 2004) from https://www.apache.org/licenses/LICENSE-2.0
