# Datalab Provider

**Provider Datalab packages a Crossplane API for platform-operated cloud workspaces.** A platform operator defines the guardrails once: ingress, identity, storage credentials, quotas, sandbox policy, network egress, and optional service classes. Teams then request a `Datalab` claim and get workspace sessions with VS Code Server, terminals, storage access, optional vclusters, and managed data services.

The package ships the **Datalab** Composite Resource Definition (XRD) and ready-to-use Crossplane v2 **Compositions**. The API is meant to be useful to software engineers and data teams, but the ownership model is operator-first: durable state, security posture, backup, capacity, and lifecycle stay visible to the platform team.

For the operating model, start with the [welcome guide](https://provider-datalab.versioneer.at/). The documentation also covers [usage concepts](https://provider-datalab.versioneer.at/latest/how-to-guides/usage_concepts/), [sandbox security](https://provider-datalab.versioneer.at/latest/security/), and [additional services](https://provider-datalab.versioneer.at/latest/how-to-guides/additional_services/) such as Dask and MLflow.

<div align="left">
  <a href="https://github.com/versioneer-tech/provider-datalab/raw/refs/heads/main/docs/imgs/datalab-vs-code-server.png" target="_blank">
    <img src="https://github.com/versioneer-tech/provider-datalab/raw/refs/heads/main/docs/imgs/datalab-vs-code-server.png" height="200" alt="Datalab - VS Code Server"/>
  </a>
</div>

Provider Datalab does not replace the tools you already operate. In the default `datalab-educates` package, most runtime features come from the excellent [Educates Training Platform](https://educates.dev/) and are packaged with Kubernetes and [Crossplane Compositions](https://docs.crossplane.io/latest/composition/compositions/). The same principle applies to storage, identity, databases, and backups: Provider Datalab exposes them through a tenant-facing API, while the operator keeps policy and accountability.

For Keycloak-managed access, Provider Datalab can create a confidential OAuth client, workspace roles, and machine/API credentials per Datalab. See the [installation guide](https://provider-datalab.versioneer.at/latest/how-to-guides/installation/#crossplane-providers-and-functions) and [authentication usage guide](https://provider-datalab.versioneer.at/latest/how-to-guides/usage_concepts/#authentication) for ingress and client-credentials details.

## Who It Is For

- **Platform operators** get a governable self-service API for workspace runtimes, security defaults, data-service classes, and lifecycle controls.
- **Software engineers and data users** get a concise `Datalab` spec instead of hand-wiring namespaces, ingress, credentials, IDE pods, databases, and registries.
- **Sponsors and governance stakeholders** get a clearer control plane: who can run code, what can persist, which services are backed up, and where policy is enforced.

## Operator Contract

A `Datalab` claim should be treated as a service contract, not only as a pod launcher. The operator decides the platform boundary in `EnvironmentConfig`, installs the required controllers, pins package versions through GitOps, and verifies that the CNI, admission policy, storage classes, backup jobs, identity system, and ingress controls match the trust model. The user-facing claim stays small because those decisions are centralized.

## API Reference

The published XRD with all fields is documented here:
👉 [API Reference Guide](https://provider-datalab.versioneer.at/latest/reference-guides/api/)

## Install the Configuration Package

You need Crossplane and the runtime prerequisites [installed](https://provider-datalab.versioneer.at/latest/how-to-guides/installation/) in your Kubernetes cluster first. Operators should manage providers, functions, Educates, Kyverno, CNI enforcement, and optional data-service operators through GitOps, then apply the configuration package.


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

Cluster-specific operator decisions are supplied via an `EnvironmentConfig`. This is where the platform sets the trust boundary for all teams using that environment.

```yaml
apiVersion: apiextensions.crossplane.io/v1beta1
kind: EnvironmentConfig
metadata:
  name: datalab
data:
  iam:
    realm: acme
  auth:
    type: delegated
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
    externalEgressCIDRs:
    - 0.0.0.0/0
    - ::/0
    serviceCIDR: "10.43.0.0/16"
    podCIDRs:
    - 10.42.0.0/16
    blacklistIPs:
    - 169.254.169.254/32
    - fd00:ec2::254/128
    - 169.254.42.42/32
    - fd00:42::42/128
    excludePolicies: []
  defaults: # optional
    quota:
      memory: 2Gi
      storage: 1Gi
      budget: medium
    security:
      policy: baseline
      kubernetesAccess: true
      kubernetesRole: edit
      externalEgress: true
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
apiVersion: pkg.internal/v1beta2
kind: Datalab
metadata:
  name: acme
  namespace: datalab
spec:
  users:
  - alice
  sessions:
  - name: default
```

If `spec.quota` or `spec.security` are omitted, values fall back to
`EnvironmentConfig.data.defaults` and then to hard defaults
(`memory=2Gi`, `storage=1Gi`, `budget=medium`,
`policy=baseline`, `kubernetesAccess=true`, `kubernetesRole=edit`,
`externalEgress=true`).
When `policy=privileged`, Docker is automatically enabled with `storage: 20Gi`.

`spec.security.externalEgress` controls whether Provider Datalab renders the
external egress policy path for all sessions and workloads in the runtime
namespace. If it is omitted, the value falls back to
`EnvironmentConfig.data.defaults.security.externalEgress` and then to the hard
default `true`, so the platform-level setting decides whether broad egress is
allowed. See [Sandbox Security Measures](docs/security/sandbox-controls.md)
for the full policy model.

Each declared session gets a Datalab-owned workspace PVC. `spec.sessions[].state`
defaults to `started`, which creates an active runtime session.
Set it to `stopped` to keep the declared session and its PVC without running
the session runtime. To choose the StorageClass for those workspace PVCs, set:

```yaml
spec:
  quota:
    storage: 20Gi
  persistence:
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
- Datalabs without declared sessions (no session PVC or runtime started by default).
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

## Breaking Changes

Since `0.6.0`:

- Datalab claims use `pkg.internal/v1beta2` because session state was introduced.
- PostgreSQL connection details are output in the datalab Secret as host-scoped keys such as `POSTGRES_<HOST>_PASSWORD` and database-scoped URLs such as `POSTGRES_<HOST>_<DBNAME>_URL`.

## License

Apache 2.0 (Apache License Version 2.0, January 2004)
<https://www.apache.org/licenses/LICENSE-2.0>
