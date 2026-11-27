# Install Provider Datalab

Run these commands from a repository checkout with access to the target
cluster. For a shared installation, manage manifests and Secrets through your
platform's GitOps and Secret tools.

## Prerequisites

The cluster needs Crossplane and Keycloak. The CNI must enforce Kubernetes
NetworkPolicy. Data and the optional registry need an S3-compatible object
store. Install an ingress or Gateway controller when public routes are enabled.
Use Crossplane from the supported range in the package's
[metadata](https://github.com/versioneer-tech/provider-datalab/blob/main/crossplane.yaml).

PostgreSQL requires CloudNativePG. Valkey uses a native StatefulSet and needs
no store operator. Install the [PostgreSQL controller](#postgresql-controller) before requesting a store;
enabled backups also need the [snapshot prerequisites](#volume-snapshots).

Gateway exposure also needs a Gateway API controller. Data uses HTTPRoute
with HTTP and TLS-terminating HTTPS listeners. External PostgreSQL access uses
`TLSRoute` in `gateway.networking.k8s.io/v1` and direct TLS with SNI.

For `spec.vclusters`, apply the supplied provider RBAC and configure an HTTPS
issuer, allowed StorageClasses, and an HTTPS Gateway listener. The package runs
vCluster OSS with the Kubernetes image pinned in the
[control-plane template](https://github.com/versioneer-tech/provider-datalab/blob/main/templates/vcluster/statefulset.yaml). The host needs
ValidatingAdmissionPolicy and BackendTLSPolicy support. Volume bindings require
host Kubernetes 1.36 or later with `admissionregistration.k8s.io/v1`
MutatingAdmissionPolicy support. See
[virtual cluster setup](vcluster.md#platform-settings).
Application owners install their controllers and workloads through the virtual
API. Use [Volumes](volumes.md) to check persistent volumes after setup.

### Dependency baseline

The package requires Crossplane 2.4.3 or later in the v2 series.
The [provider manifests](https://github.com/versioneer-tech/provider-datalab/blob/main/dependencies/02-providers.yaml)
and [function manifests](https://github.com/versioneer-tech/provider-datalab/blob/main/dependencies/functions.yaml)
contain the package versions and immutable image references. Use those files
when reviewing or changing a dependency.

Install Crossplane with the supplied Helm values from this checkout:

```bash
chart="$(python3 scripts/components.py crossplane-chart)"
helm install crossplane "${chart}" \
  --namespace crossplane \
  --create-namespace \
  --values deploy/crossplane-values.yaml \
  --post-renderer scripts/crossplane-probes.py
```

The installation commands need Python with PyYAML. Keep the supplied Helm
values and `runtimeConfigRef` settings for resource activation, Pod security,
and health checks.

The Kubernetes provider watches resources and redacts Secret data in Object
status. The composition reads source Secrets directly by namespace and name;
the supplied Crossplane role grants the required read access. If Crossplane
runs outside `crossplane`, update the ServiceAccounts and binding subjects in
`dependencies/rbac.yaml`.

When Provider Storage shares the cluster, manage shared packages, runtimes,
and RBAC in one place. Both providers use the same environment function.
Add both providers' selector labels to shared EnvironmentConfigs.

### PostgreSQL controller

PostgreSQL uses [CloudNativePG](https://cloudnative-pg.io/). Install the pinned
controller in `cnpg-system`, or set
`EnvironmentConfig.data.database.operatorNamespace` to its namespace. The
supplied provider RBAC must permit the `postgresql.cnpg.io` resources.
Use the intended platform kubeconfig and context in the install command.

```bash
chart="$(python3 scripts/components.py cnpg-chart)"
helm upgrade --install cnpg "${chart}" \
  --kubeconfig /path/to/platform.kubeconfig --kube-context platform \
  --namespace cnpg-system --create-namespace \
  --post-renderer scripts/components.py \
  --set fullnameOverride=cnpg --wait
```

Use Kubernetes `1.36` for the complete Datalab feature set and the supported
CloudNativePG range. CloudNativePG `1.30` also tests Kubernetes `1.37`, but does
not list it as supported. See its [support table](https://cloudnative-pg.io/docs/1.30/supported_releases/).

## 1. Choose the claim namespace

This guide uses `workspace` for Datalab resources and their namespaced
ProviderConfigs:

```bash
kubectl create namespace workspace
kubectl create namespace datalab
```

Input storage Secrets live in `datalab`, as set by `storage.secretNamespace`
in the environment examples. The composition creates a separate namespace
named after each Datalab for its runtime and shared services. Choose a Datalab
name that is unique across the host cluster and differs from its claim
namespace and Kubernetes system namespaces. Datalab manifests use
`apiVersion: versioneer.at/v1`.

Each service publishes a [separate connection Secret](connections.md) in the
claim namespace. Data and the registry use a storage-only Secret in the
service namespace; their OAuth2 proxy credentials remain separate.

## 2. Install provider dependencies

Apply the files in
[`dependencies/`](https://github.com/versioneer-tech/provider-datalab/tree/main/dependencies)
in this order:

| File | Purpose |
| --- | --- |
| `00-mrap.yaml` | Activate the managed resource kinds used by the composition. |
| `01-deploymentRuntimeConfigs.yaml` | Set Pod security and function message limits. |
| `02-providers.yaml` | Install the Kubernetes and Keycloak providers. |
| `03-providerConfigs.yaml` | Configure those providers in the claim namespace. |
| `functions.yaml` | Install the composition functions. |
| `rbac.yaml` | Grant provider access, admission policy management, and source Secret reads. |

Apply `03-providerConfigs.yaml` with `kubectl apply -n workspace -f ...`.
Create its referenced Keycloak credential Secret in that namespace through
your platform's Secret tools. The Keycloak account needs permission to manage
clients, client scopes, service-account roles, groups, memberships, role
mappings, and client policies in the target realm.

Use Keycloak 26.8.1 or later. Configure identity scopes, client policies, and
browser sign-in as described in [Authentication](authentication.md).
The realm must permit the built-in `offline_access` scope and user role for
[CLI device login](vcluster.md#human-access).

Use the package pins in the dependency manifests. Wait for the provider and
function revisions to report healthy before installing the configuration
package. The provider-kubernetes RBAC includes access to Pods for readiness
checks, namespaces, quotas, and service PVCs. It also installs the shared
snapshot class read role described under [Volume snapshots](#volume-snapshots).

Keep the supplied 64 MiB function message limits when you manage functions
separately. Desired and observed virtual cluster configuration is included in
pipeline requests.

## 3. Install the configuration package

Save this resource as `configuration.yaml`. Replace `<!version!>` with the
release tag you want to install.

```yaml
apiVersion: pkg.crossplane.io/v1
kind: Configuration
metadata:
  name: datalab
spec:
  package: ghcr.io/versioneer-tech/provider-datalab:<!version!>
  skipDependencyResolution: true
```

Apply it and check the package conditions:

```bash
kubectl apply -f configuration.yaml
kubectl get configurations.pkg.crossplane.io
kubectl get configurationrevisions.pkg.crossplane.io
```

The package installs the Datalab resource definition and composition. Its
providers and functions are managed separately by the platform.
The package does not contain `dependencies/rbac.yaml` or EnvironmentConfigs.
Manage them separately and apply the supplied RBAC before the configuration.

For source builds, use the
[development instructions](https://github.com/versioneer-tech/provider-datalab/blob/main/README.md#development).
Set `datalab.responseTTL` in the environment to change the Python response TTL
without rebuilding a package.

## 4. Set the shared environment

The `environmentConfigs` pipeline step uses `function-environment-configs`.
It merges the data from these EnvironmentConfigs in this order:

1. `default`, fetched directly by name. It needs no label.
2. The name in `spec.crossplane.compositionRef.name`.
3. `spec.environmentName`, when set.
4. The Datalab's `metadata.name`.

Later values override earlier values. Nested maps retain fields that later
configs do not set. Missing configs and an omitted `spec.environmentName`
are skipped.

Each config selected by the last three lookups must have the label
`datalabs.pkg.internal/name` equal to its own `metadata.name`. Add the
Provider Storage label separately when a config serves both providers.
Keep names and labels unique. Each lookup uses at most one match. If several
configs match, the function sorts by `metadata.name` and uses the first.

Use `default` for shared cluster values and `datalab` for settings
specific to this Composition. This example defines shared identity, storage,
and optional public routing:

```yaml
apiVersion: apiextensions.crossplane.io/v1beta1
kind: EnvironmentConfig
metadata:
  name: datalab
  labels:
    datalabs.pkg.internal/name: datalab
data:
  iam:
    realm: acme
    issuerURL: https://identity.acme.com/realms/acme
    internalURL: http://keycloak.keycloak:8080/realms/acme
  ingress:
    enabled: true
    domain: lab.acme.com
    secret: wildcard-tls
  oauth2Proxy:
    upstreamTimeout: 3600s
  storage:
    endpoint: https://s3.acme.com
    provider: Other
    region: us-east-1
    forcePathStyle: "true"
    secretNamespace: datalab
  network:
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
```

Replace the network ranges, endpoints, and DNS names before applying it.
Configure the [identity prerequisites](https://github.com/versioneer-tech/provider-datalab/blob/main/SECURITY.md#identity-prerequisites)
before users access the services.

### Named environment override

For a named override, set the optional `spec.environmentName`. It has no
default and accepts lowercase DNS names of 1–63 characters: letters, digits,
hyphens, and dot-separated labels, with a letter or digit at each label end.
For example:

```yaml
apiVersion: apiextensions.crossplane.io/v1beta1
kind: EnvironmentConfig
metadata:
  name: team-datalab
  labels:
    datalabs.pkg.internal/name: team-datalab
data:
  datalab:
    responseTTL: 5m
  overallQuota:
    storage: 50Gi
---
apiVersion: versioneer.at/v1
kind: Datalab
metadata:
  name: team-workspace
  namespace: workspace
spec:
  environmentName: team-datalab
  users: []
```

This override retains the other shared quota settings. A labeled config named
`team-workspace` takes precedence.

### Service addresses

Enable either `ingress.enabled` or `httpRoute.enabled` for public service
access. Using both stops reconciliation. On each Datalab's
hostname, `/v2/` serves the registry and other paths serve Data. Virtual API
routes use their instance path, such as `/.vc0`. With `httpRoute.enableS3`,
requests signed by S3 clients use the read-only S3 service on the same host.

With neither exposure method enabled, use port-forwarding to the Data
Service. The registry is available only inside the cluster.

For Ingress, supply `ingress.secret` in each Datalab service namespace. Use
your platform's certificate tools to create it. Gateway routes use the
Gateway's TLS settings.

For Gateway API exposure, replace the example's `ingress.enabled: true` with
`false` and add:

```yaml
data:
  httpRoute:
    enabled: true
    parentName: default
    parentNamespace: contour
    sectionName: workspaces-https
    httpSectionName: workspaces-http
    timeouts:
      request: 3600s
      backendRequest: 3600s
```

The Gateway needs HTTP and TLS-terminating HTTPS listeners and must accept
routes from runtime namespaces. It manages the service certificate.
For the optional read-only S3 endpoint, see [S3 client access](s3-access.md).

#### Large file transfers

`ingress.annotations` applies to both Data and registry Ingress objects. Set
upload limits and timeouts in the selected controller. The composition does
not add controller-specific annotations.

`httpRoute.timeouts` applies to Data, read-only S3, and registry backend rules.
Both timeouts default to one hour. If only `request` is set, `backendRequest`
uses that value. A nonzero backend timeout must not exceed a nonzero request
timeout. Use `0s` for both to disable these deadlines.

Gateway API has no standard body-size or buffering setting. Configure the
Gateway controller and any upstream load balancer to allow the required body
size, stream transfers, and permit long connections. The controller must
support HTTPRoute timeouts.

`oauth2Proxy.upstreamTimeout` defaults to one hour. It limits the wait for
packageR response headers after the request body is sent. It does not limit
the time to transfer the request or response body. Use `0s` to disable this
wait limit.

packageR permits all browser origins (`*`) for public catalog access.
To restrict origins, configure the Gateway to replace or remove backend CORS
headers and handle preflight requests. Adding a header does not restrict the
wildcard. Cookie-based cross-origin access needs a separate policy.

### EnvironmentConfig values and defaults

All paths below are relative to `EnvironmentConfig.data`. Defaults apply
when a setting is omitted; example values such as cluster CIDRs, endpoints,
and StorageClass names are not built-in defaults.

Set runtime options in EnvironmentConfig. Extra fields in the Datalab spec do
not override these settings.

#### Runtime and service defaults

| Setting | Default | Use |
| --- | --- | --- |
| `registry.enabled` | `false` | Shared OCI registry backed by the Datalab S3 bucket. |
| `packageR.enabled` | `true` | Shared packageR service and its configured endpoint. |
| `packageR.readOnlyMount` | `false` | Read-only application permissions when enabled; storage IAM still applies. |
| `overallQuota.storage` | `100Gi` | Aggregate PVC request limit in the Datalab service namespace. |
| `overallQuota.hard.requests.cpu` | `4` | Aggregate CPU requests in the host service namespace. |
| `overallQuota.hard.requests.memory` | `8Gi` | Aggregate memory requests in the host service namespace. |
| `overallQuota.hard.limits.cpu` | `16` | Aggregate CPU limits in the host service namespace. |
| `overallQuota.hard.limits.memory` | `32Gi` | Aggregate memory limits in the host service namespace. |
| `security.policy` | `baseline` | Pod security level: `restricted`, `baseline`, or `privileged`. |
| `security.externalEgress` | `true` | Broad egress to the configured external CIDRs. |

#### Service images

Set image overrides under `data.images` in the EnvironmentConfig. Use a full
image reference with a version tag and digest. Omitted settings use the
[source defaults](https://github.com/versioneer-tech/provider-datalab/blob/main/composition/defaults.py).

| Setting | Use |
| --- | --- |
| `images.packageR` | Data server and its init containers. |
| `images.registry` | OCI registry. |
| `images.rclone` | Data S3 service. |
| `images.postgres` | CloudNativePG-compatible PostgreSQL image with PostGIS. |
| `images.valkey` | Valkey server. |
| `images.oauth2Proxy` | OAuth2 Proxy for Data and S3. |
| `images.volumeSnapshot` | Host CSI snapshot Job. |
| `images.vclusterCleanup` | Host Pod cleanup during hibernation. |

#### Resource quotas and container defaults

The composition creates one ResourceQuota and one LimitRange in each Datalab's
host service namespace. All its services, virtual control planes, and synced
workload Pods share this quota, across all virtual namespaces and clusters.
Host admission rejects new Pods that exceed it. Quotas do not reserve capacity;
size them for the host cluster and the number of teams. Include control planes,
service sidecars, and temporary Pod overlap during rolling updates.

Override individual quota entries under `overallQuota.hard`. Unset
entries keep their defaults. Additional native ResourceQuota entries are also
accepted. `overallQuota.storage` sets the PVC request limit; an explicit
`hard.requests.storage` takes priority.

Use `limitRange.default` for missing container limits and
`limitRange.defaultRequest` for missing requests. Default limits are
CPU `1`, memory `512Mi`, and ephemeral storage `8Gi`. Default requests are
CPU `100m`, memory `128Mi`, and ephemeral storage `3Gi`. These defaults apply
to containers without the corresponding resource settings.

#### Identity and endpoints

| Setting | Default | Use |
| --- | --- | --- |
| `iam.realm` | `default` | Keycloak realm; users must already exist here. |
| `iam.namespace` | `keycloak` | Namespace selected by IAM egress rules. |
| `iam.issuerURL` | Not set | Public OIDC issuer for Data and virtual cluster access. |
| `iam.internalURL` | Not set | Token and signing-key URL; required for permanent Data exposure. |
| `iam.redirectURIs` | `[]` | Additional OAuth redirect URIs. The Data `/oauth2/callback` URI is always included. Add a localhost callback only when needed. |
| `iam.webOrigins` | `[]` | Additional browser origins. The Datalab HTTPS origin is always included. |
| `iam.extraAudiences` | `[]` | Additional audiences for tokens issued by the Datalab client. The Datalab audience is always included. |
| `ingress.enabled` | `false` | Public Data and registry Ingress. |
| `ingress.class` | Empty | Ingress class for public services. |
| `ingress.domain` | `default` | Public host suffix for services. |
| `ingress.secret` | Empty | TLS Secret; must be set for Data Ingress. |
| `ingress.annotations` | `{}` | Annotations on service Ingress objects. |
| `httpRoute.enabled` | `false` | Public Data and registry Gateway routes. |
| `httpRoute.enableS3` | `false` | Read-only S3 endpoint; requires `httpRoute.enabled`. |
| `httpRoute.parentName` | Not set | Gateway name; required when Gateway exposure is enabled. |
| `httpRoute.parentNamespace` | Not set | Gateway namespace; required when Gateway exposure is enabled. |
| `httpRoute.sectionName` | Not set | HTTPS listener; required when Gateway exposure is enabled. |
| `httpRoute.httpSectionName` | Not set | HTTP redirect listener; required when Data uses Gateway exposure. |
| `httpRoute.timeouts.request` | `3600s` | Request deadline for Data, S3, and registry routes; `0s` disables it. |
| `httpRoute.timeouts.backendRequest` | Request timeout | Deadline for each backend request, including its response body. |
| `oauth2Proxy.upstreamTimeout` | `3600s` | Wait for packageR response headers after sending the request body. |

#### Storage and managed stores

| Setting | Default | Use |
| --- | --- | --- |
| `storage.endpoint` | Empty | Endpoint reachable by runtime Pods; the input Secret's `AWS_ENDPOINT_URL` takes priority. |
| `storage.region` | Empty | Object-store region; the input Secret's `AWS_REGION` takes priority. |
| `storage.provider` | `Other` | Object-store provider for the S3 proxy. |
| `storage.forcePathStyle` | `true` | Path-style S3 requests. |
| `storage.secretNamespace` | Datalab namespace, or `default` | Input storage Secret namespace. |
| `vcluster.resources.requests` | CPU `200m`, memory `1Gi`, ephemeral storage `1Gi` | Control-plane requests; supplied fields override these defaults. |
| `vcluster.resources.limits` | CPU `4`, memory `4Gi`, ephemeral storage `10Gi` | Control-plane limits; supplied fields override these defaults. |
| `vcluster.scheduling` | `{}` | Control-plane and workload selectors and tolerations; see [placement and hibernation](vcluster.md#placement-and-hibernation). |
| `vcluster.backingStore.database.embedded` | `enabled: false`, `extraArgs: []` | Native embedded database options, including `enabled`, `dataSource`, and `extraArgs`. |
| `volumes.storage` | `1Gi` | Default size of named host PVCs. |
| `volumes.snapshotClassName` | Required for volume backups or recovery | Snapshot class for volume backups. Must use deletion policy `Delete`. |
| `volumes.schedule` | `0 1 * * *` | Backup schedule in UTC. |
| `volumes.maxSnapshots` | `2` | Completed snapshots retained per PVC UID, from 1 to 100. |
| `vcluster.storage` | `5Gi` | Default control-plane PVC size for named virtual clusters. |
| `volumes.storageClasses.allowed` | Required for volumes or virtual clusters | Allowed classes for named host volumes and virtual workloads. |
| `volumes.storageClasses.default` | First allowed class | Default class for named host volumes and virtual workloads. |
| `vcluster.storageClassName` | `volumes.storageClasses.default` | Control-plane StorageClass; must be allowed. |
| `vcluster.issuerCA` | System trust | PEM CA for the HTTPS issuer. |
| `vcluster.discoveryURL` | Issuer discovery | Optional HTTPS discovery address. |
| `vcluster.backendTLS.apiVersion` | `gateway.networking.k8s.io/v1` | BackendTLSPolicy API served by the Gateway. |
| `ingress.certificateAuthority` | System trust | PEM Gateway CA embedded in profile kubeconfigs. |
| `database.storageClassName` | Cluster default | PostgreSQL data StorageClass. |
| `database.snapshotClassName` | `volumes.snapshotClassName` | PostgreSQL snapshot class. Requires the [snapshot prerequisites](#volume-snapshots). |
| `database.schedule` | `0 0 1 * * *` | Native CNPG cold snapshot schedule. Includes seconds before minutes. |
| `database.operatorNamespace` | `cnpg-system` | CloudNativePG controller namespace for service access. |
| `database.tlsRoute.parentName` | Not set | PostgreSQL Gateway name. |
| `database.tlsRoute.parentNamespace` | Not set | PostgreSQL Gateway namespace. |
| `database.tlsRoute.sectionName` | Not set | PostgreSQL TLS listener. |
| `cacheStore.storageClassName` | Cluster default | Valkey data StorageClass. |
| `cacheStore.snapshotClassName` | `volumes.snapshotClassName` | Valkey CSI snapshot class with deletion policy `Delete`. |
| `cacheStore.schedule` | `0 1 * * *` | Valkey backup schedule in UTC. |
| `cacheStore.maxSnapshots` | `4` | Completed snapshots per data PVC UID, from 1 to 100. |

PostgreSQL TLSRoutes are created only when all three
`database.tlsRoute` settings are present.

#### Network rules

| Setting | Default | Use |
| --- | --- | --- |
| `network.externalEgressCIDRs` | `[]` | External destination ranges; empty means no broad external allow rule. |
| `network.blacklistIPs` | `[]` | CIDRs excluded from external egress. |
| `network.podCIDRs` | `[]` | Host Pod ranges excluded from external egress. |
| `network.serviceCIDR` | Not set | Host Service range excluded from external egress. |
| `network.excludePolicies` | `[]` | Generated policies to omit. |
| `network.internalEgress` | `[]` | Explicit cross-namespace destinations. |
| `network.internalIngress` | `[]` | Explicit cross-namespace sources. |
| `network.internalEgress[].namespace`, `network.internalIngress[].namespace` | Required for each entry | Peer namespace. |
| `network.internalEgress[].podSelector`, `network.internalIngress[].podSelector` | `{}` | Peer Pod selector; omitted means all Pods in the peer namespace. |
| `network.internalEgress[].ports`, `network.internalIngress[].ports` | `[]` | Ports; omitted means all ports. |
| `network.internalEgress[].ports[].port`, `network.internalIngress[].ports[].port` | Required for each port entry | Named or numbered port. |
| `network.internalEgress[].ports[].protocol`, `network.internalIngress[].ports[].protocol` | Kubernetes default (`TCP`) | Port protocol. |
| `network.internalEgress[].ports[].endPort`, `network.internalIngress[].ports[].endPort` | Not set | End of a numeric port range. |
| `network.internalIngress[].targetPodSelector` | `{}` | Runtime Pods selected by the ingress policy; omitted means all runtime Pods. |

### Secret exports

`customSecrets` lists optional sources for native virtual Secret bindings.
See [connection bindings](connections.md#bind-a-connection).

### Network access

See [Network access in SECURITY.md](https://github.com/versioneer-tech/provider-datalab/blob/main/SECURITY.md#network-access)
for host network ranges, cross-namespace rules, and policy checks.

## 5. Supply storage credentials

Create the object-storage bucket and credentials through your platform's
storage process or [Provider Storage](https://provider-storage.versioneer.at/).
Provider Datalab reads an existing input Secret with the same name as the Datalab.

The Secret must exist in `storage.secretNamespace` and contain
`AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`. The storage identity must
permit bucket listing with `s3:ListAllMyBuckets`. The endpoint must support
path-style S3 requests.

The registry needs a bucket with the same name as the Datalab and permission
to read, write, list, delete, and use multipart uploads. Distribution uses its
standard object layout without an extra prefix or PVC. Disabling the registry
retains its S3 objects. The registry is disabled by default. Set
`registry.enabled: true` only when the platform provides this storage.

For a manual setup, create the Secret with your credential values:

```bash
kubectl -n datalab create secret generic s-joe \
  --from-literal=AWS_ACCESS_KEY_ID='<KEY_ID>' \
  --from-literal=AWS_SECRET_ACCESS_KEY='<SECRET>'
```

Use the platform's Secret tools for shared installations. Keep live
credentials out of Git.

## 6. Create a Datalab

Save this resource as `datalab.yaml`. The user `joe` must already exist in
Keycloak. This uses the [Joe example](https://github.com/versioneer-tech/provider-datalab/blob/main/examples/base/001-lab.yaml)
with an explicit claim namespace.

```yaml
apiVersion: versioneer.at/v1
kind: Datalab
metadata:
  name: s-joe
  namespace: workspace
spec:
  users:
  - joe
```

Apply it and check its conditions:

```bash
kubectl apply -f datalab.yaml
kubectl get datalabs -n workspace
kubectl describe datalab s-joe -n workspace
```

See [Use a Datalab](usage_concepts.md) for volume, managed services, and sharing.

## 7. Check the installation

Check that provider and function revisions are healthy and that the
Datalab reports `Synced=True` and `Ready=True`:

```bash
kubectl get providers.pkg.crossplane.io
kubectl get providerrevisions.pkg.crossplane.io
kubectl get functions.pkg.crossplane.io
kubectl get functionrevisions.pkg.crossplane.io
kubectl get configurations.pkg.crossplane.io
kubectl get configurationrevisions.pkg.crossplane.io
kubectl get datalabs -n workspace
```

If reconciliation fails, read the Datalab conditions and events. Check that
the required APIs are served. The provider APIs used here are namespaced:

```bash
kubectl api-resources --api-group=kubernetes.m.crossplane.io
kubectl api-resources --api-group=keycloak.m.crossplane.io
kubectl api-resources --api-group=gateway.networking.k8s.io
```

For a managed store, also check its API group from the prerequisite table.
Verify the Data address, storage access, and each requested service before
giving users access. For virtual clusters, also check user login, application
installation, and [volume persistence](volumes.md).

## Volume snapshots

Volume backups run on the host and need a snapshot-capable CSI driver, its
snapshotter sidecar, the common snapshot controller, and the v1
`VolumeSnapshot`, `VolumeSnapshotContent`, and `VolumeSnapshotClass` CRDs. Create a matching `VolumeSnapshotClass` with `deletionPolicy: Delete`
so retention can remove old snapshots. The host must also serve
`ValidatingAdmissionPolicy` for the source PVC guards.

Configure the operator policy in EnvironmentConfig:

```yaml
data:
  volumes:
    storage: 1Gi
    storageClasses:
      allowed: [workspace-storage]
      default: workspace-storage
    snapshotClassName: workspace-snapshots
    schedule: '0 1 * * *'
    maxSnapshots: 2
```

The PVC's StorageClass and the VolumeSnapshotClass must use the same CSI driver.
No second PVC or StorageClass is needed for backups. The policy applies to named
volumes with `backups: true`. See [Backup policy](volumes.md#backup-policy)
for limits and failure handling.

See [Volume backup access in SECURITY.md](https://github.com/versioneer-tech/provider-datalab/blob/main/SECURITY.md#volume-backup-access)
for the required roles, API network access, and backup identity.

Test restore with the deployed CSI driver before relying on it. See
[Volumes](volumes.md) for status, recovery, and deletion.

For a virtual cluster, the platform must expose these APIs and classes and
permit snapshot and restore operations through the virtual API. For shared-node vCluster, enable `sync.toHost.volumeSnapshots`,
`sync.toHost.volumeSnapshotContents`, and `sync.fromHost.volumeSnapshotClasses`,
with the required syncer RBAC. CRDs and classes alone do not forward snapshot
requests. See [vCluster volume snapshots](https://www.vcluster.com/docs/vcluster/configure/sync/to-host/storage/volume-snapshots).
