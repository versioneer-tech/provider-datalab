# Provider Datalab

**Provider Datalab provides a Crossplane API for shared data environments.**
Teams can collaborate on object-storage data, request managed services such as
PostgreSQL and Redis, and optionally start compute sessions with a hosted VS
Code instance and Kubernetes access. Object storage can be provisioned through
[Provider Storage](https://provider-storage.versioneer.at/) or another storage
service.

Platform operators define the available services and set the rules for
identity, ingress, storage, quotas, network access, security, backup, and
lifecycle. See the [Provider Datalab documentation](https://provider-datalab.versioneer.at/)
for the operating model, configuration, and examples.

<div align="left">
  <a href="https://github.com/versioneer-tech/provider-datalab/raw/refs/heads/main/docs/imgs/datalab-vs-code-server.png" target="_blank">
    <img src="https://github.com/versioneer-tech/provider-datalab/raw/refs/heads/main/docs/imgs/datalab-vs-code-server.png" height="200" alt="Datalab - VS Code Server"/>
  </a>
</div>

The default `datalab-educates` package uses the [Educates Training Platform](https://educates.dev/) for workspace sessions. [Crossplane Compositions](https://docs.crossplane.io/latest/composition/compositions/) connect it to the platform's storage, identity, and data services. Operators configure and maintain those services.

The platform ingress layer handles session authentication and authorization. Provider Datalab creates a confidential Keycloak OAuth client, workspace roles, and machine/API credentials for each Datalab. The generated client is useful for Datalab-scoped automation and for protecting services owned by that Datalab; shared browser ingress can also use a central platform OAuth client. See the [installation guide](https://provider-datalab.versioneer.at/latest/how-to-guides/installation/#crossplane-providers-and-functions) and [authentication usage guide](https://provider-datalab.versioneer.at/latest/how-to-guides/usage_concepts/#authentication) for ingress and client-credentials details.

## Who It Is For

- **Platform operators** configure available services, access rules, resource limits, and backups.
- **Software engineers and data users** request workspaces and data services through one `Datalab` spec.
- **Service owners** can review who has access, what data is stored, and how it is backed up.

## Platform Setup

The operator sets shared defaults in `EnvironmentConfig`, installs the required controllers, and manages package versions through GitOps. Before users create Datalabs, check network policy, storage, backups, identity, and ingress access against the platform's requirements.

## API Reference

The published XRD with all fields is documented here:
👉 [API Reference Guide](https://provider-datalab.versioneer.at/latest/reference-guides/api/)

## Install the Configuration Package

You need Crossplane and the runtime prerequisites [installed](https://provider-datalab.versioneer.at/latest/how-to-guides/installation/) in your Kubernetes cluster first. Operators should manage providers, functions, Educates, CNI enforcement, optional admission policy, and optional data-service operators through GitOps, then apply the configuration package.

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

Use an `EnvironmentConfig` to set shared platform settings for all teams in an environment.

```yaml
apiVersion: apiextensions.crossplane.io/v1beta1
kind: EnvironmentConfig
metadata:
  name: datalab
data:
  iam:
    realm: acme
    issuerURL: https://identity.acme.com/realms/acme
    internalURL: http://identity.identity-system.svc/realms/acme
  ingress:
    enabled: true
    class: nginx
    domain: lab.acme.com
    secret: wildcard-tls
    annotations: {} # optional controller-specific Ingress annotations
  storage:
    endpoint: https://s3.acme.com
    forcePathStyle: "true"
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
    overallQuota:
      storage: 100Gi
    security:
      policy: baseline
      kubernetesAccess: true
      kubernetesRole: edit
      externalEgress: true
  database:
    tlsRoute: # optional (only needed if database should be externally accessible)
      parentName: default
      parentNamespace: gateway-system
      sectionName: database-tls
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

`spec.overallQuota.storage` sets the aggregate PVC requested-storage quota for
the Datalab environment namespace. It falls back to
`EnvironmentConfig.data.defaults.overallQuota.storage` and then to `100Gi`.
The quota is namespace-scoped and does not cover PVCs in other namespaces.

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

`spec.data.enabled` enables one shared `package-r` service. Its UI can browse S3,
create temporary download URLs, and share object prefixes with optional
passwords.

Enable `EnvironmentConfig.data.ingress.enabled` for a permanent Kubernetes
Ingress, or `httpRoute.enabled` for Gateway API HTTPRoutes. Enable only one.
Both require `iam.issuerURL`, `iam.internalURL`, and `ingress.domain`.
Ingress requires `ingress.class` and `ingress.secret`; HTTPRoute requires
listener references and Gateway-managed TLS. Missing values stop
reconciliation and appear in the Datalab status.

Share data with the world by putting it in your Datalab's `public` folder
and sending the public link. Anyone can browse and download those files without
signing in. See [Sharing Data with the World](docs/how-to-guides/usage_concepts.md#sharing-data-with-the-world)
for the folder location and an example.

`spec.data.readOnlyMount: true` keeps the default read-only permissions. A
`false` value grants create, delete, modify, and rename permissions. The S3 IAM
policy takes precedence.

**Experimental:** With `httpRoute.enabled: true`, set
`httpRoute.enableS3: true` to enable
the read-only S3 endpoint for all Data-enabled Datalabs in that environment.
Browser and S3 requests use the same hostname. There is no per-Datalab S3
setting. See [S3 client access](docs/how-to-guides/usage_concepts.md#s3-client-access).

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

The platform's installed operators manage these services. Configure monitoring, backups, upgrades, and deletion for each service you offer.

### More examples

See these [`example manifests`](examples/base) for complete scenarios, including:

- Datalabs without declared sessions (no session PVC or runtime started by default).
- Datalabs with sessions and optional vCluster API isolation.
- Registry-enabled and registry-disabled runtime examples.
- Datalabs with managed PostgreSQL databases, document stores, cache stores, and vector stores.
- Datalabs with workshop files fetched from Git, OCI images, or HTTP archives.

## Storage Credentials

Provider Datalab expects object-storage credentials to already exist. Buckets and credentials can be created manually or with [provider-storage](https://github.com/versioneer-tech/provider-storage).

The `storage` section in the `EnvironmentConfig` tells Provider Datalab where to read the Secret. The composition reads the Secret named by `spec.secretName`, or the `Datalab` name when `spec.secretName` is omitted. The Secret must exist in `storage.secretNamespace` and include at least:

- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`

The values must provide access to the storage endpoint listed in
`EnvironmentConfig.data.storage` (for example, `endpoint`, `region`, and
`provider`). `package-r` uses `endpoint` for direct S3 requests.

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
