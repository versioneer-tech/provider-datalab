# Datalab Provider

**Provider Datalab is a PaaS-style building block for platform operators:** it turns one `Datalab` claim into an end-user workspace with an online IDE, object-storage access, managed databases, document stores, key-value/cache stores, vector databases, and an optional Docker registry. Users get a smooth workspace. Operators keep visibility into what was provisioned, so they can own access, capacity, lifecycle, and backups.

This package provides the **Datalab** Composite Resource Definition (XRD) and ready-to-use Crossplane v2 **Compositions** for provisioning multi-user, multi-runtime data labs.

## The Goal

Give platform operators one simple API for collaborative data labs. Teams should not have to assemble runtime pods, identity bindings, storage credentials, databases, and supporting services by hand.

As the operator, you install the Crossplane configuration package, set cluster defaults in an `EnvironmentConfig`, and decide which services are available: **ingress**, **file storage** (e.g. NFS), an **IAM system** or delegated authentication layer, object-storage credentials, and optional operators for PostgreSQL, MongoDB, Redis, and Qdrant.

Provider Datalab does **not** create object-storage buckets itself. For bucket and credential provisioning, use [provider-storage](https://github.com/versioneer-tech/provider-storage) or another storage process. Provider Datalab consumes the resulting credentials and wires object-storage access into the workspace.

Each `Datalab` manifest is the contract for a tenant or team. It can define users, sessions, quotas, security settings, files, storage access, and stateful services. The generated resources stay visible in Kubernetes and Crossplane, so operators can apply policies, monitor them, and decide how durable services are backed up.

The user-facing side stays simple. A `Datalab` can be created with `kubectl`, GitOps, or higher-level tooling such as the [Workspaces](https://github.com/EOEPCA/workspace) Building Block. Users then get **VS Code Server**, terminals, object-storage access, preloaded files, and optional managed services.

Keycloak-managed access is supported, with workspace clients, groups, roles, role bindings, and memberships automatically provisioned by the composition. Authentication can also be delegated to the ingress or platform identity layer, for example with `oauth2-proxy`, when that layer already owns the user lifecycle.

You can provide object-storage credentials directly per team, or let [provider-storage](https://github.com/versioneer-tech/provider-storage) provision buckets and credentials first. Beyond the built-in runtime and storage access, users can deploy [additional services](https://provider-datalab.versioneer.at/latest/how-to-guides/additional-services/) through the Kubernetes API - for example **MLflow** or **Dask**. With **vCluster**, they can also deploy tools that need cluster-wide resources such as `CRDs` or `RBAC cluster roles`.

<div align="left">
  <a href="https://github.com/versioneer-tech/provider-datalab/raw/refs/heads/main/docs/imgs/datalab-vs-code-server.png" target="_blank">
    <img src="https://github.com/versioneer-tech/provider-datalab/raw/refs/heads/main/docs/imgs/datalab-vs-code-server.png" height="200" alt="Datalab - VS Code Server"/>
  </a>
</div>

✨ For a full introduction, see the [documentation](https://provider-datalab.versioneer.at/).

Provider Datalab does not replace the tools you already operate. In the default `datalab-educates` package, most runtime features come from the excellent [Educates Training Platform](https://educates.dev/) and are packaged with Kubernetes and [Crossplane Compositions](https://docs.crossplane.io/latest/composition/compositions/). The same principle applies to storage, identity, databases, and backups: Provider Datalab exposes them through a tenant-facing API, while the operator keeps ownership and policy.

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

Cluster-specific settings are supplied via an `EnvironmentConfig`.

```yaml
apiVersion: apiextensions.crossplane.io/v1beta1
kind: EnvironmentConfig
metadata:
  name: datalab
data:
  iam:
    realm: acme
  auth:
    type: none
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
  storageClasses:
    allowed:
    - sbs-default
    - sbs-default-retain
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

Session workspace PVCs are ephemeral by default and follow Educates' normal
`WorkshopSession` lifecycle. To keep `/home/eduk8s` across session deletion,
opt into a Datalab-owned PVC:

```yaml
spec:
  quota:
    storage: 20Gi
  persistence:
    ephemeral: false
    storageClassName: sbs-default
```

When `EnvironmentConfig.data.storageClasses.allowed` is non-empty, the requested
StorageClass is used only if it appears in that list; otherwise Provider Datalab
uses the first allowed class. If the list is omitted or empty, any requested
StorageClass is allowed and an omitted `storageClassName` lets Kubernetes use
the cluster default.

### Optional managed services

The same claim can request durable platform services:

```yaml
spec:
  databases:
    pg0:
      names:
      - analytics
      storage: 1Gi
      backupStorage: 3Gi
  documentStores:
    prod:
      storage: 1Gi
  cacheStores:
    prod:
      storage: 1Gi
  vectorStores:
    prod:
      storage: 1Gi
  registry:
    enabled: true
    storage: 3Gi
```

These services stay visible to the operator, so they can be monitored, backed up, upgraded, and retired intentionally.

### More examples

See these [`example manifests`](examples/base) for complete scenarios, including:
- Datalabs without sessions (no runtime started by default).
- Datalabs with sessions and optional vcluster isolation.
- Registry-enabled and registry-disabled runtime examples.
- Datalabs with managed PostgreSQL databases, document stores, cache stores, and vector stores.
- Datalabs with workshop files fetched from Git, OCI images, or HTTP archives.

## Storage Credentials

Provider Datalab expects object-storage credentials to already exist. Buckets and credentials can be created manually or with [provider-storage](https://github.com/versioneer-tech/provider-storage).

The `storage` section in the `EnvironmentConfig` tells Provider Datalab where to read the Secret. The composition reads the Secret named by `spec.secretName`, or the `Datalab` name when `spec.secretName` is omitted. The Secret must exist in `storage.secretNamespace` and include at least:

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
