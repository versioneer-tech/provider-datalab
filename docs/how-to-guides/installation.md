# Provider Datalab – Installation Guide

The `provider-datalab` configuration packages let you provision **collaborative data labs** on Kubernetes, using either **Educates** or **Jupyter** runtimes.  
Labs, sessions, storage, and identity are declared via a single, namespaced `Datalab` spec.

---

## Namespacing Model (Important)

Everything in this guide is **namespaced**:

- You **apply** `Datalab` claims **to a namespace** (e.g., `workspace`).  
- The **referenced Secret for storage** lives in the same namespace as the `Datalab` claim (Secret name = `spec.secretName`).  
- Any **namespaced ProviderConfigs** or supporting objects that the compositions depend on **must exist in that same target namespace** (e.g., `workspace`).  

> In short: choose your target namespace (e.g., `workspace`), apply the provider configs there, and create your `Datalab` claims in that namespace.

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

- **Educates installed with all CRDs in the cluster** if you plan to use the Educates runtime.  
  See the [Educates Installation Guide](https://educates.dev/docs/installation/) for details.  
- **JupyterHub / Jupyter Operator installed** if you plan to use the Jupyter runtime (upcoming integration).  

Without the corresponding runtime installed, Datalab claims for that variant will not reconcile.

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

When installed, a Datalab will provision a vcluster (if enabled) and launch the Educates tooling stack (VS Code Server, terminal, storage browser, plus preinstalled tools like `awscli` and `rclone`).

---

### Jupyter Runtime (upcoming)

Upcoming integration!

---

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
  ingress:
    class: nginx
    domain: datalab.demo
    secret: wildcard-tls
  storage:
    endpoint: https://s3.demo
    provider: Other
    region: demo
    force_path_style: "true"
    secretNamespace: datalab
    type: s3
  network:
    serviceCIDR: "10.43.0.0/16"
```

The `serviceCIDR` defines the internal Service network range expected by the vCluster’s API server. In the Datalab setup, the host cluster’s DNS and networking are reused, and no separate CoreDNS is deployed inside the vCluster. Using the host’s `serviceCIDR` therefore reduces startup time and control-plane overhead, since CoreDNS doesn’t need to start separately within each vCluster.

To find the correct value, use the same `serviceCIDR` as your host cluster — it’s typically visible in your cluster configuration or can be inferred by checking CoreDNS’s Service IP via `kubectl get svc kube-dns -n kube-system`.

---

## Step 4 – Storage credentials

The `storage` section in the `EnvironmentConfig` references a Kubernetes Secret — **named identically to `spec.secretName` in the Datalab** — which must already exist in the cluster.  
This Secret must reside in the namespace specified by `storage.secretNamespace` and include at least:

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

kubectl get managedresourcedefinitions | grep -E 'helm|kubernetes|keycloak'

kubectl get xrd
kubectl get datalabs.pkg.internal -A
```
