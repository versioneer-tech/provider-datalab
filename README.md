# Datalab Provider

This package provides the **Datalab** Composite Resource Definition (XRD) and ready-to-use Crossplane v2 **Compositions** for provisioning multi-user, multi-runtime data labs.

## The Goal

Make life easier for you as an operator by offering ready-to-use **runtime environments** for your end users. All you need is a Kubernetes cluster with **ingress**, **file storage** (e.g. NFS), an **IAM system** (currently only Keycloak is supported), and - for the actual data - **object storage credentials** — whether from an in-cluster service like `MinIO` or an external provider like `AWS S3` or `OTC OBS`. You can provide that directly per team or use the accompanying [provider-storage](https://github.com/versioneer-tech/provider-storage), where object storage access can be automatically provisioned and injected in a way that integrates seamlessly with the `Datalab` environment.

With just a few settings in the global environment configuration, you can deploy a `Datalab` manifest directly to your cluster through the Kubernetes API — for example, using `kubectl`. Alternatively, use higher-level tooling such as the [Workspaces](https://github.com/EOEPCA/workspace) Building Block, which provides a thin API and UI layer on top. Within minutes, your users can launch their own `Datalab` as a working environment. If required, PostgreSQL databases can also be automatically provisioned and optionally exposed externally (since version 0.3.0).

Beyond the built-in **VS Code Server** and integrated object storage access, users can extend their environments by deploying [additional services](https://provider-datalab.versioneer.at/latest/how-to-guides/additional-services/) directly via the Kubernetes API — from **MLflow** for experiment tracking to **Dask** for scalable data processing. Thanks to **vCluster** support, they can even deploy services **requiring cluster-wide resources** such as `CRDs` or `RBAC cluster roles` — as for example needed by the Dask Gateway Helm chart.

<div align="left">
  <a href="https://github.com/versioneer-tech/provider-datalab/raw/refs/heads/main/docs/imgs/datalab-vs-code-server.png" target="_blank">
    <img src="https://github.com/versioneer-tech/provider-datalab/raw/refs/heads/main/docs/imgs/datalab-vs-code-server.png" height="200" alt="Datalab - VS Code Server"/>
  </a>
</div>

✨ For a full introduction, see the [documentation](https://provider-datalab.versioneer.at/).

The Datalab Provider does not introduce new functionality or tooling — in its default form with `datalab-educates`, most functional capabilities are powered by the excellent [Educates Training Platform](https://educates.dev/) project, integrated through Kubernetes and [Crossplane Compositions](https://docs.crossplane.io/latest/composition/compositions/) into a reusable building block, as outlined in our blog [Building Data Supply Chains with Lego Bricks](https://medium.com/@stefan.achtsnit_41940/building-data-supply-chains-with-lego-bricks-why-earth-observation-needs-composable-infrastructure-38600b920bb6).

## API Reference

The published XRD with all fields is documented here:  
👉 [API Reference Guide](https://provider-datalab.versioneer.at/latest/reference-guides/api/)

## Install the Configuration Package

You need Crossplane and some prerequisites [installed](https://provider-datalab.versioneer.at/latest/how-to-guides/installation/) in your Kubernetes cluster. Then you only need to apply the configuration package to your cluster. Providers and functions should typically be managed by your GitOps process.


```yaml
apiVersion: pkg.crossplane.io/v1
kind: Configuration
metadata:
  name: datalab
spec:
  package: ghcr.io/versioneer-tech/provider-datalab/educates:latest
  skipDependencyResolution: true
```

## Environment Configuration

Cluster-specific settings are supplied via an `EnvironmentConfig`. The Datalab composition consumes this in its `prepare-environment` step.

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
  storage:
    endpoint: https://s3.acme.com
    force_path_style: "true"
    provider: Other
    region: acme
    secretNamespace: datalab
    type: s3
  network: # optional
    serviceCIDR: "10.43.0.0/16"
  defaults: # optional
    quota:
      memory: 2Gi
      storage: 1Gi
      budget: medium
    security:
      policy: baseline
      kubernetesAccess: true
      kubernetesRole: edit
  database: 
    gateway: # optional (only needed if database should be externally accessible)
      parentName: default
      parentNamespace: projectcontour
      sectionName: postgres-passthrough
    storageClassName: ""
    backupStorageClassName: ""
  
```

## Datalab Spec

### Minimal example

```yaml
apiVersion: pkg.internal/v1beta1
kind: Datalab
metadata:
  name: acme
  namespace: datalab
spec:
  users:
  - alice
  sessions:
  - default
```

If `spec.quota` or `spec.security` are omitted, values fall back to  
`EnvironmentConfig.data.defaults` and then to hard defaults  
(`memory=2Gi`, `storage=1Gi`, `budget=medium`,  
`policy=baseline`, `kubernetesAccess=true`, `kubernetesRole=edit`).  
When `policy=privileged`, Docker is automatically enabled with `storage: 20Gi`.

### More examples

See these [`example manifests`](examples/base) for complete scenarios, including:
- Datalabs without sessions (no runtime started by default).
- Datalabs with sessions and optional vcluster isolation.
- Datalabs with workshop files fetched from Git, OCI images, or HTTP archives.

## Storage Credentials

The `storage` section in the `EnvironmentConfig` references a Kubernetes Secret — named identically to the Datalab — which must already exist in the cluster.  
This Secret must reside in the namespace specified by `storage.secretNamespace` and include at least the following keys:

- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`

The values must provide access to the storage endpoint listed in `EnvironmentConfig.data.storage` (e.g. `endpoint`, `region`, `provider`).

You can create this secret manually, for example:

```bash
kubectl -n datalab create secret generic <DATALAB> \
  --from-literal=AWS_ACCESS_KEY_ID=<KEY_ID> \
  --from-literal=AWS_SECRET_ACCESS_KEY=<SECRET>
```

## License

Apache 2.0 (Apache License Version 2.0, January 2004)  
<https://www.apache.org/licenses/LICENSE-2.0>
