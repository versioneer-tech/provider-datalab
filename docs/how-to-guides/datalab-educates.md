# An Educates based Datalab variant — How‑To Guide

This guide explains how to install the **Datalab** Crossplane package for the Educates runtime, provide cluster‑specific settings, and provision your first lab. The approach is **platform‑engineering first**: a single CRD abstracts identity, ingress, storage, and content bootstrapping while you choose the runtime stack.

## 1) Prerequisites

- Kubernetes cluster with `kubectl` access
- Crossplane **v2.0.2** or newer, installed and healthy
- A GitOps mechanism (optional but recommended) to manage Providers/Functions
- DNS/TLS and an ingress controller in your cluster (any implementation)

## 2) Install the Datalab configuration package

Install the configuration package. Providers and functions are managed separately:

```yaml
apiVersion: pkg.crossplane.io/v1
kind: Configuration
metadata:
  name: datalab
spec:
  package: ghcr.io/versioneer-tech/provider-datalab/educates:latest
  skipDependencyResolution: true
```

Apply:

```bash
kubectl apply -f configuration-install.yaml
kubectl get configurationrevisions.pkg.crossplane.io
```

## 3) Runtime dependencies

This Datalab targets the **Educates** runtime. See this [README](https://github.com/versioneer-tech/provider-datalab/tree/main/educates/dependencies) for instructions to install Educates and the Crossplane v2 dependencies.

## 4) Environment configuration

Provide cluster‑specific settings through an `EnvironmentConfig`. The composition consumes this to render ingress, identity, and storage correctly:

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
```

## 5) Storage credentials

The `storage` section in the `EnvironmentConfig` references a Kubernetes Secret — **named identically to the Datalab** — which must already exist in the cluster.  
This Secret must reside in the namespace specified by `storage.secretNamespace` and include at least:

- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`

The credentials must provide access to the endpoint/region defined in the environment config. You can create the secret manually, for example:

```bash
kubectl -n datalab create secret generic demo   --from-literal=AWS_ACCESS_KEY_ID=<KEY_ID>   --from-literal=AWS_SECRET_ACCESS_KEY=<SECRET>
```

## 6) Create a Datalab

The minimal example creates a user‑scoped lab with one session. Sessions are required to start a runtime; if omitted, no runtime is started by default (you may patch sessions later). If `spec.files` is empty or omitted, **no workshop tab** is rendered in the Educates UI.

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

For more scenarios, see these[`example manifests`](https://github.com/versioneer-tech/provider-datalab/blob/main/examples/labs.yaml), which demonstrates:
- labs with multiple users
- enabling/disabling `spec.vcluster`
- attaching workshop files from Git, OCI images, or HTTP sources

## 7) Validate installation

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

**Key:**  
- Sessions present → runtime is started; none → no runtime until patched  
- Files present → workshop tab enabled; none → no workshop tab  
- `spec.vcluster: true` → vcluster provisioned; `false` → namespace‑scoped runtime
