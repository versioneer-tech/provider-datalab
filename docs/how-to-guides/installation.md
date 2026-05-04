# Provider Datalab – Installation Guide

The `provider-datalab` configuration package lets platform operators expose **collaborative data labs** on Kubernetes as a PaaS-style building block. Labs, sessions, storage access, identity, and optional managed services are declared through one namespaced `Datalab` spec. The operator still owns the backing services, policies, and backup model.

---

## Namespacing Model (Important)

Everything in this guide is **namespaced**:

- You **apply** `Datalab` claims **to a namespace** (e.g., `workspace`).
- The **referenced Secret for storage** lives in the namespace configured by `EnvironmentConfig.data.storage.secretNamespace`, normally the same namespace as the `Datalab` claim. The Secret name is `spec.secretName`, or the `Datalab` name when `spec.secretName` is omitted.
- Any **namespaced ProviderConfigs** or supporting objects that the compositions depend on **must exist in that same target namespace** (e.g., `workspace`).

> In short: choose your target namespace (e.g., `workspace`), apply the provider configs there, create or provision the referenced object-storage credentials there, and create your `Datalab` claims in that namespace.

---

## Prerequisites

- A running Kubernetes cluster (e.g., `kind`, managed K8s).
- `kubectl` access.
- **Crossplane** installed in the cluster:

```bash
helm repo add crossplane-stable https://charts.crossplane.io/stable
helm repo update
helm install crossplane \
  --namespace crossplane-system \
  --create-namespace crossplane-stable/crossplane \
  --version 2.0.2 \
  --set provider.defaultActivations={}
```

- **Educates installed with all CRDs in the cluster**  for the Educates runtime.
  See the [Educates Installation Guide](https://educates.dev/docs/installation/) for details.
- **Crunchy PostgreSQL Operator installed** if you plan to use `spec.databases` (Postgres feature).
  Suggested tested line: PGO `v5.8.x` (or your cluster-validated equivalent).
- **MongoDB Kubernetes Operator installed** if you plan to use `spec.documentStores` (document store feature).
  Suggested tested line: MongoDB Operator `v1.7.x` (or your cluster-validated equivalent).
  The operator installation must provide its own controller RBAC; `provider-datalab` only creates namespace-local Mongo prerequisites such as service accounts, a Role, and an appdb RoleBinding inside the tenant namespace.
- **Redis Kubernetes Operator installed** if you plan to use `spec.cacheStores` (cache store feature).
  Suggested tested line: Redis Operator `v0.21.x` (or your cluster-validated equivalent).
- **Qdrant Kubernetes Operator installed** if you plan to use `spec.vectorStores` (vector store feature).
  Suggested tested line: Qdrant Operator `v1.15.x` (or your cluster-validated equivalent).

Without the corresponding optional database operators installed, `spec.databases`, `spec.documentStores`, `spec.cacheStores`, and/or `spec.vectorStores` cannot reconcile.

Treat these optional operators as platform service classes. If you enable a field in the `Datalab` API, make sure the operations model is ready too: storage classes, backup and restore, monitoring, upgrades, and tenant lifecycle.

> To reduce control-plane load, we use a `ManagedResourceActivationPolicy` (MRAP) per backend so only the needed Managed Resources are active.

---

## Step 1 – Install Provider Dependencies (per runtime)

All runtimes follow the same staged pattern you **must** install **before** the configuration package:
1. **ManagedResourceActivationPolicy** – activate only the resource kinds that are needed.
2. **Deployment Runtime Configs** – define how providers/functions run.
3. **Providers** – install the required Crossplane providers.
4. **ProviderConfigs** (namespaced) – configure providers in your target namespace.
5. **Functions** – install supporting Crossplane Functions.
6. **RBAC** – permissions for `provider-kubernetes` to observe and reconcile objects.

The `provider-kubernetes` RBAC must also allow Pod and PVC access in tenant namespaces. Pod access is required for the Redis and Qdrant readiness observers; PVC access is required when Datalab creates durable Educates session volumes.

Repository root: <https://github.com/versioneer-tech/provider-datalab/>

---

### Educates Runtime

> You operate the Educates training platform in your cluster. Ensure **Educates is installed with all CRDs** before proceeding.

Provider dependencies activate Helm, Kubernetes, and Keycloak resources as needed:

- [00-mrap.yaml](https://github.com/versioneer-tech/provider-datalab/blob/main/educates/dependencies/00-mrap.yaml) – Activate Educates-specific Managed Resources.
- [01-deploymentRuntimeConfigs.yaml](https://github.com/versioneer-tech/provider-datalab/blob/main/educates/dependencies/01-deploymentRuntimeConfigs.yaml) – Runtime configs for providers/functions.
- [02-providers.yaml](https://github.com/versioneer-tech/provider-datalab/blob/main/educates/dependencies/02-providers.yaml) – Install Helm, Kubernetes, and Keycloak providers.
- [03-providerConfigs.yaml](https://github.com/versioneer-tech/provider-datalab/blob/main/educates/dependencies/03-providerConfigs.yaml) – **Apply in your target namespace** (e.g., `workspace`); sets up storage and identity configs.
- [functions.yaml](https://github.com/versioneer-tech/provider-datalab/blob/main/educates/dependencies/functions.yaml) – Functions used by compositions.
- [rbac.yaml](https://github.com/versioneer-tech/provider-datalab/blob/main/educates/dependencies/rbac.yaml) – RBAC for `provider-kubernetes`.

Recommended Crossplane dependency set for `datalab-educates`:
- Providers:
  - `provider-kubernetes` (`xpkg.upbound.io/crossplane-contrib/provider-kubernetes`)
  - `provider-helm` (`xpkg.upbound.io/crossplane-contrib/provider-helm`)
  - `provider-keycloak` (`ghcr.io/crossplane-contrib/provider-keycloak`)
- Functions:
  - `crossplane-contrib-function-python`
  - `crossplane-contrib-function-auto-ready`

Pin exact provider and function versions or digests in your GitOps source and upgrade them intentionally after validation.

Keycloak-managed access is supported: the composition automatically provisions the workspace client, groups, roles, role bindings, and memberships. At the same time, the provider is intentionally only a workspace provisioning building block. In many production deployments it is better to delegate authentication to the platform, for example to the ingress layer with `oauth2-proxy`, while keeping `auth.type = none` in the Datalab environment configuration.

When Keycloak-managed access is used, the target realm is configured with `EnvironmentConfig.data.iam.realm`, and the `provider-keycloak` `ProviderConfig` must point at a reachable Keycloak instance with permissions to manage clients, groups, group memberships, roles, and protocol mappers in that realm. Users accessing a workspace do not necessarily have to exist in Keycloak when authentication is delegated to another platform component.

When installed, a Datalab will provision a vcluster (if enabled), launch the Educates tooling stack (VS Code Server, terminal, storage browser, plus tools like `awscli` and `rclone`), wire in object-storage credentials, and reconcile any requested platform-managed data services.

## Step 2 – Install the Configuration Package (after dependencies)

Once the provider dependencies are in place, install the configuration package for your chosen runtime. This registers the `Datalab` CRD and compositions and allows immediate reconciliation because the providers/configs already exist.

**Example – Educates**

```yaml
apiVersion: pkg.crossplane.io/v1
kind: Configuration
metadata:
  name: datalab-educates
spec:
  package: ghcr.io/versioneer-tech/provider-datalab/educates:<!version!>
  skipDependencyResolution: true
```

Apply:

```bash
kubectl apply -f configuration.yaml
```

---

## Step 3 – Environment configuration

Provide cluster-specific settings through an `EnvironmentConfig`. The composition consumes this to render ingress, identity, and storage correctly:

```yaml
apiVersion: apiextensions.crossplane.io/v1beta1
kind: EnvironmentConfig
metadata:
  name: datalab
data:
  iam:
    realm: demo
  auth:
    # Use "credentials" to reuse storage credentials, or "none" when
    # the ingress/platform layer handles authentication.
    type: none
  ingress:
    class: nginx
    domain: datalab.acme.org
    secret: wildcard-tls
  storage:
    endpoint: https://s3.demo
    provider: Other
    region: demo
    force_path_style: "true"
    secretNamespace: datalab
    type: s3
  storageClasses:
    allowed:
    - sbs-default
    - sbs-default-retain
  network:
    serviceCIDR: "10.43.0.0/16"
```

The default `EnvironmentConfig` name is `datalab`. To use a different one for a specific `Datalab`, set `datalabs.pkg.internal/environment` as an annotation or label on that `Datalab`.

`storageClasses.allowed` is an optional allowlist for durable session PVCs. If it is set, Provider Datalab uses a requested StorageClass only when it is listed there; otherwise it falls back to the first entry. If the list is omitted or empty, any requested StorageClass is allowed.

The `serviceCIDR` defines the internal Service network range expected by the vCluster’s API server. In the Datalab setup, the host cluster’s DNS and networking are reused, and no separate CoreDNS is deployed inside the vCluster. Using the host’s `serviceCIDR` therefore reduces startup time and control-plane overhead, since CoreDNS doesn’t need to start separately within each vCluster.

To find the correct value, use the same `serviceCIDR` as your host cluster — it’s typically visible in your cluster configuration or can be inferred by checking CoreDNS’s Service IP via `kubectl get svc kube-dns -n kube-system`.

Apply dependency manifests in order so that later objects can reference earlier ones cleanly: MRAP first, then deployment runtime configs, providers, namespaced provider configs, functions, and finally RBAC. After each dependency stage, wait for the corresponding `ProviderRevision` or `FunctionRevision` to become healthy before moving on.

Manage provider credentials and storage secrets through your normal secret-management path, such as External Secrets or Sealed Secrets, rather than committing live credentials into Git. If you use [Provider Storage](https://provider-storage.versioneer.at/), let it create the bucket and credentials, then reference those credentials from the `Datalab`.

---

## Step 4 – Storage credentials

Provider Datalab does not create object-storage buckets. Create the bucket and credentials manually, through your platform process, or with [Provider Storage](https://provider-storage.versioneer.at/).

The `storage` section in the `EnvironmentConfig` tells Provider Datalab where to read the credentials. The composition reads the Secret named by `spec.secretName`, or the `Datalab` name when `spec.secretName` is omitted. This Secret must exist in `storage.secretNamespace` and include at least:

- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`

Create it manually, for example:

```bash
kubectl -n datalab create secret generic demo \
  --from-literal=AWS_ACCESS_KEY_ID=<KEY_ID> \
  --from-literal=AWS_SECRET_ACCESS_KEY=<SECRET>
```

---

## Step 5 – Create a Datalab

The minimal example creates a user-scoped lab with one session.
- Sessions present → a runtime is automatically started until stopped by the operator.
- No sessions → no runtime is started until the user explicitly launches one.
- Files present → workshop tab enabled; none → no workshop tab.
- `spec.vcluster: true` → vcluster provisioned; `false` → namespace-scoped runtime.

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
  vcluster: true
  files: []
```

For more scenarios, see these [`example manifests`](https://github.com/versioneer-tech/provider-datalab/blob/main/examples/base), which demonstrate:
- labs with multiple users
- enabling/disabling `spec.vcluster`
- attaching workshop files from Git, OCI images, or HTTP sources

---

## Step 6 – Validate installation

Check that packages, providers, CRDs, and your XRD are healthy:

```bash
kubectl get providers.pkg.crossplane.io
kubectl get providerrevisions.pkg.crossplane.io

kubectl get configurations.pkg.crossplane.io
kubectl get configurationrevisions.pkg.crossplane.io

kubectl api-resources --api-group=kubernetes.crossplane.io
kubectl api-resources --api-group=helm.crossplane.io
kubectl api-resources --api-group=keycloak.crossplane.io
kubectl api-resources --api-group=postgres-operator.crunchydata.com
kubectl api-resources --api-group=mongodbcommunity.mongodb.com
kubectl api-resources --api-group=redis.redis.opstreelabs.in
kubectl api-resources --api-group=qdrant.io

kubectl get managedresourcedefinitions | grep -E 'helm|kubernetes|keycloak'

kubectl get xrd
kubectl get datalabs.pkg.internal -A
```
