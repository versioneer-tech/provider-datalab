# Datalab — How‑To Guide (Crossplane v2)

This guide shows how to install the **Datalab** Crossplane package, wire cluster‑specific settings, and provision your first data lab. The approach is **platform‑engineering first**: a single CRD abstracts the details of identity, ingress, storage, and content bootstrapping, while you remain free to choose the runtime stack.

## 1) Prerequisites

- Kubernetes cluster with `kubectl` access.
- Crossplane **v2.0.2** or newer installed and healthy.
- A GitOps mechanism (optional but recommended) to manage Providers/Functions.
- DNS/TLS and an ingress controller in your cluster (any implementation).

## 2) Install the Datalab configuration package

Install the package and **disable dependency resolution** (you will manage Providers/Functions yourself):

```yaml
apiVersion: pkg.crossplane.io/v1
kind: Configuration
metadata:
  name: datalab
spec:
  package: ghcr.io/versioneer-tech/provider-datalab/educates:<!version!>
  skipDependencyResolution: true
```

Apply:
```bash
kubectl apply -f configuration-install.yaml
kubectl get configurationrevisions.pkg.crossplane.io
```

## 3) Install Dependencies (runtime setup)

See `educates/dependencies/README.md`.

## 4) Environment configuration

Use a namespaced `EnvironmentConfig` to pass cluster‑specific settings to the composition:

```yaml
apiVersion: apiextensions.crossplane.io/v1beta1
kind: EnvironmentConfig
metadata:
  name: config
data:
  iam:
    realm: demo
  ingress:
    class: nginx
    domain: datalab.demo
    secret: wildcard-tls
  storage:
    secretRef: s3-credentials
```

**Field semantics**

- `iam.realm`: group/namespace for identities.
- `ingress.class`: ingress class name.
- `ingress.domain`: base domain for hostnames.
- `ingress.secret`: TLS Secret used by routes.
- `storage.secretRef`: Secret name holding S3‑compatible credentials.

## 5) Storage credentials

Create the Secret (example):

```bash
kubectl -n <NAMESPACE> create secret generic s3-credentials   --from-literal=AWS_ACCESS_KEY_ID=<KEY_ID>   --from-literal=AWS_SECRET_ACCESS_KEY=<SECRET>   --from-literal=AWS_REGION=<REGION>   --from-literal=AWS_ENDPOINT_URL=<https://s3.example.com>   --from-literal=AWS_S3_FORCE_PATH_STYLE=true
```

Override the name via `EnvironmentConfig.data.storage.secretRef`, or create it as `workspace` to use the default.

## 6) Create a Datalab

**Minimal**
```yaml
apiVersion: pkg.internal/v1beta1
kind: Datalab
metadata:
  name: demo
  namespace: demo
spec:
  owner: alice
```

**With members and file bundles**
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
  - image:
      url: ghcr.io/acme/lab-assets:2025.09
    includePaths:
      - /data/**
      - /README.md
    path: .
```

**Source options (recap)**

- `image`: `url` (required), optional `secretRef`, `dangerousSkipTLSVerify`, `tagSelection.semver`

```yaml
- image:
    url: ghcr.io/acme/lab-assets:2025.09
  includePaths:
    - /data/**
    - /README.md
  path: .
```

- `git`: `url` + `ref` (required), optional `refSelection.semver`, `lfsSkipSmudge`, `verification.publicKeysSecretRef`, `secretRef`

```yaml
- git:
    url: https://github.com/acme/lab-assets
    ref: origin/main
  newRootPath: /data
  includePaths: ["/**"]
```

- `http`: `url` (required), optional `sha256`, `secretRef`

```yaml
- http:
    url: https://downloads.example.com/data.tar.gz
  includePaths: ["/**"]
  path: ./data
```

## 7) Validation & smoke tests

```bash
# Package and revision health
kubectl get configurations.pkg.crossplane.io
kubectl get configurationrevisions.pkg.crossplane.io

# Providers and CRDs
kubectl get providers.pkg.crossplane.io
kubectl get providerrevisions.pkg.crossplane.io
kubectl api-resources --api-group=kubernetes.crossplane.io
kubectl api-resources --api-group=helm.crossplane.io
kubectl api-resources --api-group=keycloak.crossplane.io

# MRDs
kubectl get managedresourcedefinitions | grep -E 'helm|kubernetes|keycloak'

# Your XRD / XR
kubectl get xrd
kubectl get datalabs.pkg.internal
```
