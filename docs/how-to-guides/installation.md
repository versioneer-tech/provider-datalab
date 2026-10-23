# Install Provider Datalab

This guide prepares the platform, installs the configuration package, and
creates a first Datalab. Run the commands with access to the target cluster.
Use your platform's GitOps and Secret tools for a shared installation.

## Prerequisites

The cluster needs Crossplane, Educates, an ingress controller, Keycloak, and
an S3-compatible object store. The CNI must enforce Kubernetes NetworkPolicy.
Use Crossplane from the supported range in the package's
[metadata](https://github.com/versioneer-tech/provider-datalab/blob/main/educates/crossplane.yaml).

Install Educates with its CRDs and controller RBAC before creating Datalabs.
Follow the [Educates installation guide](https://docs.educates.dev/en/stable/installation-guides/installation-instructions.html).
The Educates ingress class, domain, and TLS Secret must match the settings
below.

Install the operators for the managed stores you plan to offer:

| Datalab field | Operator | Required resource API |
| --- | --- | --- |
| `spec.databases` | Crunchy PostgreSQL Operator | `PostgresCluster` in `postgres-operator.crunchydata.com/v1` |
| `spec.documentStores` | MongoDB Kubernetes Operator | `MongoDBCommunity` in `mongodbcommunity.mongodb.com/v1` |
| `spec.cacheStores` | Redis Kubernetes Operator | `Redis` in `redis.redis.opstreelabs.in/v1beta2` |
| `spec.vectorStores` | Qdrant Operator | `QdrantCluster` in `qdrant.io/v1alpha1` |

Check the served APIs and fields before upgrading an operator. The
[integration tests](https://github.com/versioneer-tech/provider-datalab/tree/main/tests/integration)
contain the dependency settings used by this repository. Configure storage,
backup and restore, monitoring, and deletion for each store you offer.

Gateway exposure also needs a Gateway API controller. Data uses HTTPRoute
with HTTP and TLS-terminating HTTPS listeners. External PostgreSQL access uses
`TLSRoute` in `gateway.networking.k8s.io/v1` and direct TLS with SNI.

## 1. Choose the claim namespace

This guide uses `workspace` for Datalab resources and their namespaced
ProviderConfigs:

```bash
kubectl create namespace workspace
```

The input storage Secret lives in `storage.secretNamespace`, set below.
This guide also uses `workspace` for that namespace. Educates creates the
runtime namespaces when the Datalab is reconciled.

## 2. Install provider dependencies

Apply the files in
[`educates/dependencies/`](https://github.com/versioneer-tech/provider-datalab/tree/main/educates/dependencies)
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
clients, service-account roles, groups, memberships, and role mappings in the
target realm.

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
  name: datalab-educates
spec:
  package: ghcr.io/versioneer-tech/provider-datalab/educates:<!version!>
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

## 4. Set the shared environment

Create an `EnvironmentConfig` named `datalab` with values for your cluster.
This example uses a permanent Data Ingress:

```yaml
apiVersion: apiextensions.crossplane.io/v1beta1
kind: EnvironmentConfig
metadata:
  name: datalab
data:
  iam:
    realm: demo
    issuerURL: https://identity.example.org/realms/demo
    internalURL: http://keycloak.keycloak:8080/realms/demo
  ingress:
    enabled: true
    class: nginx
    domain: lab.example.org
    secret: wildcard-tls
    annotations: {}
  storage:
    endpoint: https://s3.example.org
    provider: Other
    region: us-east-1
    forcePathStyle: "true"
    secretNamespace: workspace
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
    overallQuota:
      storage: 100Gi
    security:
      externalEgress: true
```

Replace the example storage classes, network ranges, and DNS names before
applying it. To select another EnvironmentConfig for one Datalab, set its
`datalabs.pkg.internal/environment` annotation or label to that config's name.

### Identity

Set `iam.realm` to the Keycloak realm that contains your users. The public
`iam.issuerURL` is used for browser login; `iam.internalURL` is used for
in-cluster token and signing-key requests. The IAM namespace defaults to
`keycloak`. Set `iam.namespace` if your installation uses another namespace.

Provider Datalab creates a confidential OAuth client, groups, roles, and
memberships for each Datalab. Platform ingress policy must protect session
access. See [Authentication](authentication.md) for the role model and the
controller examples.

### Data address

`ingress.enabled` and `httpRoute.enabled` both default to `false`. In that
case, a session reaches Data through its Educates-authenticated ingress.
Enable one setting to give each Datalab a permanent Data address. Enabling
both stops reconciliation.

Both options need `iam.issuerURL`, `iam.internalURL`, and `ingress.domain`.
An Ingress also needs `ingress.class` and `ingress.secret`. Use
`ingress.annotations` for controller settings.

For Gateway API exposure, merge this block into the EnvironmentConfig:

```yaml
data:
  ingress:
    enabled: false
    class: nginx
    domain: lab.example.org
    secret: wildcard-tls
  httpRoute:
    enabled: true
    enableS3: false
    parentName: default
    parentNamespace: gateway-system
    sectionName: workspaces-https
    httpSectionName: workspaces-http
```

The Gateway needs HTTP and TLS-terminating HTTPS listeners and must accept
routes from Datalab runtime namespaces. It manages the permanent Data
certificate. Keep `ingress.class` and `ingress.secret` for Educates session
Ingress objects.

Set `httpRoute.enableS3: true` to add the experimental read-only S3 endpoint
for every Data-enabled Datalab in the environment. Browser and S3 requests
then use the same hostname. See [S3 client access](s3-access.md) for the
controller requirements and client setup.

### Public catalog CORS

packageR allows all browser origins (`*`) for public catalog access. No chart
or EnvironmentConfig CORS setting is needed. To restrict origins, configure
the Gateway to replace or remove backend CORS headers and handle preflight
requests. Adding another CORS header does not restrict the wildcard.
Check the controller's support for
[HTTPRoute CORS filters](https://gateway-api.sigs.k8s.io/guides/user-guides/http-cors/).
Cookie-based cross-origin access needs its own policy.

### Storage and quotas

`storage.endpoint` is the S3 address used by session tools and packageR.
It must be reachable from the runtime Pods. Browsers connect to Data rather
than directly to object storage. Use `storage.forcePathStyle` when the store
requires path-style addresses.

`storageClasses.allowed` restricts the classes used by session PVCs. A
requested class is used when listed; otherwise the first listed class is
used. With an empty or omitted list, any requested class is allowed.

`defaults.overallQuota.storage` sets the total PVC request limit for each
Datalab environment namespace. A Datalab can override it with
`spec.overallQuota.storage`. If neither is set, the limit is `100Gi`.
PVCs in other namespaces are outside that quota.

### Network access

Set `network.podCIDRs` and `network.serviceCIDR` to the host cluster's network
ranges. They are excluded from broad external egress so that it does not also
allow access to other Datalab namespaces. Use the cluster configuration for
the Service CIDR. A DNS Service IP alone does not identify the full range.
Pod CIDRs can be listed with:

```bash
kubectl get nodes -o jsonpath='{range .items[*]}{.metadata.name}{"  "}{.spec.podCIDR}{"  "}{.spec.podCIDRs}{"\n"}{end}'
```

`network.externalEgressCIDRs` lists the external ranges allowed when
`externalEgress` is true. Use `0.0.0.0/0` and `::/0` for all external IPv4 and
IPv6 addresses, or list narrower ranges. An empty list grants no broad
external access. `network.blacklistIPs` excludes ranges such as cloud
metadata endpoints from that rule.

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

Data uses these rules to reach object storage. The Data and S3 proxies also
have an IAM egress rule for TCP port 8080 in the configured IAM namespace.
When replacing a manual IAM policy, verify the composed policy and an S3 read
before removal, then repeat the read without the manual policy.

Use `network.excludePolicies` only when another policy system supplies the
same controls. See [Network policies](../security/sandbox-controls.md) for
the generated policies and how they combine.

## 5. Supply storage credentials

Create the object-storage bucket and credentials through your platform's
storage process or [Provider Storage](https://provider-storage.versioneer.at/).
Provider Datalab reads an existing input Secret. Its name comes from
`spec.secretName`, or the Datalab name when that field is omitted.

The Secret must exist in `storage.secretNamespace` and contain
`AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`. The storage identity must
permit bucket listing with `s3:ListAllMyBuckets`. The endpoint must support
path-style S3 requests.

For a manual setup, create the Secret with your credential values:

```bash
kubectl -n workspace create secret generic demo \
  --from-literal=AWS_ACCESS_KEY_ID=<KEY_ID> \
  --from-literal=AWS_SECRET_ACCESS_KEY=<SECRET>
```

Use the platform's Secret tools for shared installations. Keep live
credentials out of Git.

## 6. Create a Datalab

Save this resource as `datalab.yaml`. Alice must already exist in Keycloak.

```yaml
apiVersion: pkg.internal/v1beta2
kind: Datalab
metadata:
  name: demo
  namespace: workspace
spec:
  users:
  - alice
  sessions:
  - name: default
```

Apply it and check its conditions:

```bash
kubectl apply -f datalab.yaml
kubectl get datalabs -n workspace
kubectl describe datalab demo -n workspace
```

The default session starts and gets a workspace PVC. Its Data tab opens the
shared file browser. With the permanent address enabled, users can also open
Data without a session and publish files through the default public share.
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
Then verify the session login, Data address, storage access, and each requested
service before giving the Datalab to users.
