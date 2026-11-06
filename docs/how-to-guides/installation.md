# Install Provider Datalab

Run these commands from a repository checkout with access to the target
cluster. For a shared installation, manage manifests and Secrets through your
platform's GitOps and Secret tools.

## Prerequisites

The cluster needs Crossplane, the Educates session runtime, an ingress
controller, Keycloak, and an S3-compatible object store. The CNI must enforce
Kubernetes NetworkPolicy.
Use Crossplane from the supported range in the package's
[metadata](https://github.com/versioneer-tech/provider-datalab/blob/main/crossplane.yaml).

Install the session runtime with its CRDs and controller RBAC before creating
Datalabs. Follow the [runtime installation guide](https://docs.educates.dev/en/stable/installation-guides/installation-instructions.html).
The runtime ingress class, domain, and TLS Secret must match the settings
below.

Install the operators for the managed stores you plan to offer. Provider
Datalab integration tests use these versions:

| Datalab field | Operator | Test version | Required resource API |
| --- | --- | --- | --- |
| `spec.databases` | Crunchy PostgreSQL Operator (PGO) | `6.0.2` | `PostgresCluster` in `postgres-operator.crunchydata.com/v1` |
| `spec.documentStores` | MongoDB Kubernetes Operator | `1.14.0` | `MongoDBCommunity` in `mongodbcommunity.mongodb.com/v1` |
| `spec.cacheStores` | Opstree Redis Operator | `0.27.0` (Helm chart `0.27.0`) | `Redis` in `redis.redis.opstreelabs.in/v1beta2` |

These are fixed test pins. Other versions need validation before use.

Install each operator's CRDs before its controller. The
[integration harness](https://github.com/versioneer-tech/provider-datalab/blob/main/tests/integration/README.md) shows the tested
installation settings. Backup volumes need a StorageClass that supports
`ReadWriteOnce`; see [backup settings](usage_concepts.md#backups).

Gateway exposure also needs a Gateway API controller. Data uses HTTPRoute
with HTTP and TLS-terminating HTTPS listeners. External PostgreSQL access uses
`TLSRoute` in `gateway.networking.k8s.io/v1` and direct TLS with SNI.

For `spec.vclusters`, apply the supplied provider RBAC and configure an HTTPS
issuer, allowed StorageClasses, and an HTTPS Gateway listener. The host needs
ValidatingAdmissionPolicy and BackendTLSPolicy support. See
[virtual cluster setup](vcluster.md#platform-settings).

## 1. Choose the claim namespace

This guide uses `workspace` for Datalab resources and their namespaced
ProviderConfigs:

```bash
kubectl create namespace workspace
kubectl create namespace datalab
```

Input storage Secrets live in `datalab`, as set by `storage.secretNamespace`
in the environment examples. Each Datalab also has a separate namespace for
its runtime and shared services.

## 2. Install provider dependencies

Apply the files in
[`dependencies/`](https://github.com/versioneer-tech/provider-datalab/tree/main/dependencies)
in this order:

| File | Purpose |
| --- | --- |
| `00-mrap.yaml` | Activate the managed resource kinds used by the composition. |
| `01-deploymentRuntimeConfigs.yaml` | Set provider and function Pod security. |
| `02-providers.yaml` | Install the Kubernetes, Helm, and Keycloak providers. |
| `03-providerConfigs.yaml` | Configure those providers in the claim namespace. |
| `functions.yaml` | Install the composition functions. |
| `rbac.yaml` | Grant provider-kubernetes access to the resources it manages. |

Apply `03-providerConfigs.yaml` with `kubectl apply -n workspace -f ...`.
Create its referenced Keycloak credential Secret in that namespace through
your platform's Secret tools. The Keycloak account needs permission to manage
clients, client scopes, service-account roles, groups, memberships, role
mappings, and client policies in the target realm.

Use Keycloak 26.2 or later. Configure identity scopes, client policies, and
browser sign-in as described in [Authentication](authentication.md).

Use the package pins in the dependency manifests. Wait for the provider and
function revisions to report healthy before installing the configuration
package. The provider-kubernetes RBAC includes access to Pods for readiness
checks and PVCs for session storage.

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

For a source installation, apply `xrd.yaml` before `composition.yaml` so
Kubernetes retains the [OAuth2 discovery](authentication.md#oauth2-discovery)
fields.

The [manifest build guide](https://github.com/versioneer-tech/provider-datalab/blob/main/templates/README.md) explains how to change
the pipeline response TTL before building a package.

## 4. Set the shared environment

Create an `EnvironmentConfig` named `datalab` with values for your cluster.
This example uses NGINX Ingress for Data and the registry:

```yaml
apiVersion: apiextensions.crossplane.io/v1beta1
kind: EnvironmentConfig
metadata:
  name: datalab
data:
  iam:
    realm: acme
    issuerURL: https://identity.acme.com/realms/acme
    internalURL: http://keycloak.keycloak:8080/realms/acme
  ingress:
    enabled: true
    class: nginx
    domain: lab.acme.com
    secret: wildcard-tls
    annotations:
      nginx.ingress.kubernetes.io/proxy-body-size: "0"
      nginx.ingress.kubernetes.io/proxy-request-buffering: "off"
      nginx.ingress.kubernetes.io/proxy-buffering: "off"
      nginx.ingress.kubernetes.io/proxy-read-timeout: "3600"
      nginx.ingress.kubernetes.io/proxy-send-timeout: "3600"
  oauth2Proxy:
    upstreamTimeout: 3600s
  storage:
    endpoint: https://s3.acme.com
    provider: Other
    region: us-east-1
    forcePathStyle: "true"
    secretNamespace: datalab
    type: s3
  storageClasses:
    allowed:
    - sbs-default
    - sbs-default-retain
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
  defaults:
    vcluster:
      enabled: true
    registry:
      enabled: true
    data:
      enabled: true
      readOnlyMount: false
    overallQuota:
      storage: 100Gi
    security:
      externalEgress: true
```

Replace the example storage classes, network ranges, and DNS names before
applying it. Configure [authentication](authentication.md) before users start
sessions.

### Service addresses

Enable either `ingress.enabled` or `httpRoute.enabled` for public service
access. Using both stops reconciliation. On each Datalab's
hostname, `/v2/` serves the registry and other paths serve Data. Virtual API
routes use their instance path, such as `/.vc0`. With `httpRoute.enableS3`,
requests signed by S3 clients use the read-only S3 service on the same host.

With neither exposure method enabled, Data is available through a session's
authenticated ingress. The registry is available only inside the cluster.

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
Keep the ingress class and TLS Secret set for the session runtime. For the
optional read-only S3 endpoint, see [S3 client access](s3-access.md).

#### Large file transfers

`ingress.annotations` applies to both Data and registry Ingress objects. The
example permits any upload size, streams requests and responses, and allows
one hour between read or write operations. These annotations require the
community ingress-nginx controller. Use your controller's settings if you
use another implementation. The composition does not add controller-specific
annotations.

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

Select a specific EnvironmentConfig with the
`datalabs.pkg.internal/environment` annotation or label to use its settings
without per-Datalab overrides, as shown in the
[`datalab-custom` example](https://github.com/versioneer-tech/provider-datalab/blob/main/examples/base/003-lab.yaml).
The annotation takes priority over the label; the default selection is `datalab`.

Runtime settings come from the EnvironmentConfig. The XRD retains unknown
fields, but extra fields in `spec` do not override these settings.

#### Runtime and service defaults

| Setting | Default | Use |
| --- | --- | --- |
| `defaults.vcluster.enabled` | `true` | Virtual Kubernetes API for each started session. |
| `defaults.registry.enabled` | `true` | Shared OCI registry backed by the Datalab S3 bucket. |
| `defaults.data.enabled` | `true` | Shared packageR service and its configured endpoint. |
| `defaults.data.readOnlyMount` | `false` | Read-only application permissions when enabled; storage IAM still applies. |
| `defaults.quota.memory` | `2Gi` | Session memory request. |
| `defaults.quota.storage` | `1Gi` | Workspace PVC size. |
| `defaults.quota.budget` | `medium` | Session namespace budget. |
| `defaults.overallQuota.storage` | `100Gi` | Aggregate PVC request limit in the environment namespace. |
| `defaults.security.policy` | `baseline` | Pod security level: `restricted`, `baseline`, or `privileged`. |
| `defaults.security.kubernetesAccess` | `true` | Session Kubernetes service account token. |
| `defaults.security.kubernetesRole` | `edit` | Session role: `view`, `edit`, or `admin`. |
| `defaults.security.externalEgress` | `true` | Broad egress to the configured external CIDRs. |
| `defaults.persistence.storageClassName` | First allowed class, or cluster default | Workspace StorageClass; a value outside the allowlist falls back to its first entry. |
| `defaults.files` | `[]` | Workshop file bundles. |
| `packages` | `[]` | Session extension packages. |

Session PVC names and namespaces are listed in `status.sessions[].pvcRef`.
`status.sessions[].pvcSize` reports the requested size.

File bundles and extension packages are passed to the session runtime
unchanged. Set Data enablement before creating Datalabs because the runtime
saves each environment's Workshop specification. See [file sources](usage_concepts.md#files-and-the-workshop-tab)
for a file bundle example.

#### Service images

Set these image references under `data.images` in the EnvironmentConfig.
Use a full image reference with a tag or digest. Omitted settings use the
defaults below.

| Setting | Default image tag | Use |
| --- | --- | --- |
| `images.packageR` | `ghcr.io/versioneer-tech/package-r:vnext.1.1.0` | Data server and its database init container. |
| `images.registry` | `registry:3.1.2` | CNCF Distribution registry. |
| `images.rclone` | `rclone/rclone:1.71.0` | Data S3 service. Session extension packages are configured separately. |
| `images.mongo` | `quay.io/mongodb/mongodb-community-server:8.0.12-ubi8` | MongoDB server. The default database version is `8.0.12`. |
| `images.mongoBackup` | `mongo:8.0.12` | MongoDB backup tools. If omitted, its tag follows the database version. |
| `images.redis` | `quay.io/opstree/redis:v7.0.15` | Redis server and its init container. |
| `images.redisBackup` | `redis:7.0.15` | Redis backup tools. |
| `images.oauth2Proxy` | `quay.io/oauth2-proxy/oauth2-proxy:v7.15.4` | OAuth2 Proxy for Data and S3. |

The default OAuth2 Proxy image is also pinned by digest in the composition.
A MongoDB image tag that starts with `major.minor.patch` sets the database
version. For a digest without a version tag, set
`documentStore.version` to the image's MongoDB version. Use compatible server
and backup images.

#### Identity and endpoints

| Setting | Default | Use |
| --- | --- | --- |
| `iam.realm` | `default` | Keycloak realm; users must already exist here. |
| `iam.namespace` | `keycloak` | Namespace selected by IAM egress rules. |
| `iam.issuerURL` | Not set | Public OIDC issuer for Data and virtual cluster access. |
| `iam.internalURL` | Not set | Token and signing-key URL; required for permanent Data exposure. |
| `iam.extraAudiences` | `[]` | Additional audiences for tokens issued by the Datalab client. The Datalab audience is always included. |
| `ingress.enabled` | `false` | Public Data and registry Ingress. |
| `ingress.class` | Empty | Ingress class for sessions and services. |
| `ingress.domain` | `default` for sessions | Public host suffix for sessions and services. |
| `ingress.secret` | `wildcard-tls` for sessions | TLS Secret; must be set for Data Ingress. |
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
| `storage.type` | Empty | rclone backend type, usually `s3`. |
| `storage.provider` | Empty for rclone; `Other` for the S3 proxy | Object-store provider. |
| `storage.forcePathStyle` | `true` | Path-style S3 requests. |
| `storage.secretNamespace` | Datalab namespace, or `default` | Input storage Secret namespace. |
| `storageClasses.allowed` | `[]` | Allowed workspace StorageClasses; an empty list permits any configured class. |
| `vcluster.resources.requests` | CPU `200m`, memory `1Gi`, ephemeral storage `1Gi` | Control-plane requests; supplied fields override these defaults. |
| `vcluster.resources.limits` | CPU `4`, memory `4Gi`, ephemeral storage `10Gi` | Control-plane limits; supplied fields override these defaults. |
| `vcluster.backingStore.database.embedded` | `enabled: false`, `extraArgs: []` | Native embedded database options, including `enabled`, `dataSource`, and `extraArgs`. |
| `vcluster.storage` | `5Gi` | Default control-plane PVC size for named virtual clusters. |
| `vcluster.storageClasses.allowed` | Required when virtual clusters are declared | Host classes exposed to virtual workloads. |
| `vcluster.storageClasses.default` | First allowed class | Virtual workload default class. |
| `vcluster.storageClassName` | Virtual default class | Control-plane StorageClass; must be allowed. |
| `vcluster.issuerCA` | System trust | PEM CA for the HTTPS issuer. |
| `vcluster.discoveryURL` | Issuer discovery | Optional HTTPS discovery address. |
| `vcluster.backendTLS.apiVersion` | `gateway.networking.k8s.io/v1` | BackendTLSPolicy API served by the Gateway. |
| `ingress.certificateAuthority` | System trust | PEM Gateway CA embedded in profile kubeconfigs. |
| `database.storageClassName` | Cluster default | PostgreSQL data StorageClass. |
| `database.backupStorageClassName` | Cluster default | PostgreSQL backup StorageClass. |
| `database.tlsRoute.parentName` | Not set | PostgreSQL Gateway name. |
| `database.tlsRoute.parentNamespace` | Not set | PostgreSQL Gateway namespace. |
| `database.tlsRoute.sectionName` | Not set | PostgreSQL TLS listener. |
| `documentStore.version` | `8.0.12`, or version from `images.mongo` | Database version; set it for an image without a version tag. |
| `documentStore.storageClassName` | Cluster default | MongoDB data StorageClass. |
| `documentStore.backupStorageClassName` | Cluster default | MongoDB backup StorageClass. |
| `cacheStore.storageClassName` | Cluster default | Redis data StorageClass. |
| `cacheStore.backupStorageClassName` | Cluster default | Redis backup StorageClass. |

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

### Network access

Set `network.podCIDRs` and `network.serviceCIDR` to the host cluster's network
ranges. They are excluded from broad external egress so that it does not also
allow access to other Datalab namespaces. Use the cluster configuration for
the Service CIDR. A DNS Service IP alone does not identify the full range.
Pod CIDRs can be listed with:

```bash
kubectl get nodes -o jsonpath='{range .items[*]}{.metadata.name}{"  "}{.spec.podCIDR}{"  "}{.spec.podCIDRs}{"\n"}{end}'
```

Use `0.0.0.0/0` and `::/0` for all external IPv4 and IPv6 destinations,
or list narrower ranges in `network.externalEgressCIDRs`.

For a backend Pod in another namespace, add an `internalEgress` entry:

```yaml
network:
  internalEgress:
  - namespace: minio
    podSelector:
      matchLabels:
        v1.min.io/tenant: default
    ports:
    - protocol: TCP
      port: 443
    - protocol: TCP
      port: 9000
```

Use `network.internalIngress` for inbound traffic. It uses the same fields as
`internalEgress`, with `namespace` and `podSelector` selecting the source:

```yaml
network:
  internalIngress:
  - namespace: operations
    podSelector:
      matchLabels:
        app.kubernetes.io/name: prometheus
    targetPodSelector:
      matchLabels:
        app.kubernetes.io/name: package-r
    ports:
    - protocol: TCP
      port: 8888
```

These rules apply to existing runtime namespaces too. See
[Network policies](../security/sandbox-controls.md) for how policies combine,
Data access, and policy exclusions.

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
retains its S3 objects. Set `defaults.registry.enabled: false` when the
platform does not provide this storage.

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
apiVersion: pkg.internal/v1beta2
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

See [Use a Datalab](usage_concepts.md) for session state, managed services,
workshop files, and sharing.

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
kubectl api-resources --api-group=helm.m.crossplane.io
kubectl api-resources --api-group=keycloak.m.crossplane.io
kubectl api-resources --api-group=gateway.networking.k8s.io
```

For a managed store, also check its API group from the prerequisite table.
Verify the Data address, storage access, and each requested service. If you
declared a session, also check its browser login before giving users access.
