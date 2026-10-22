# Provider Datalab – Installation Guide

Provider Datalab creates shared data workspaces on Kubernetes. Users request sessions, storage access, and optional managed services through a namespaced `Datalab` spec. This guide covers the platform setup, dependencies, and shared settings.

---

## Namespaces

Choose a namespace for Datalab claims and their supporting configuration:

- You **apply** `Datalab` claims **to a namespace** (e.g., `workspace`).
- The **referenced Secret for storage** lives in the namespace configured by `EnvironmentConfig.data.storage.secretNamespace`, normally the same namespace as the `Datalab` claim. The Secret name is `spec.secretName`, or the `Datalab` name when `spec.secretName` is omitted.
- Any **namespaced ProviderConfigs** or supporting objects that the compositions depend on **must exist in that same target namespace** (e.g., `workspace`).

Apply the ProviderConfigs in the chosen namespace. Create storage credentials in the configured storage Secret namespace before you create the Datalab claims.

---

## Prerequisites

Before installation, choose which services to offer. The workspace runtime needs Crossplane, Educates, a CNI that enforces network policy, ingress, identity, and object storage. Enable optional databases and stores after their operators, backups, and maintenance procedures are ready.

- A running Kubernetes cluster (e.g., `kind`, managed K8s).
- `kubectl` access.
- **A CNI that enforces Kubernetes NetworkPolicy**. The generated Datalab policies are useful only when the dataplane enforces them.
- **Crossplane** installed in the cluster:

```bash
helm repo add crossplane-stable https://charts.crossplane.io/stable
helm repo update
helm install crossplane \
  --namespace crossplane-system \
  --create-namespace crossplane-stable/crossplane \
  --version 2.4.1 \
  --set provider.defaultActivations={}
```

The configuration package supports Crossplane `v2.0.0` or later. The package
metadata does not restrict later major versions. Crossplane `v2.4.1` is the
version used by this repository's current tests and the installation example
above; it is not the minimum supported version. Validate upgrades through your
normal platform test process.

The supplied dependency manifests and tests use the following tested pins:

| Dependency | Tested version |
| --- | --- |
| Crossplane | `v2.4.1` |
| provider-kubernetes | `v1.3.1` |
| provider-helm | `v1.0.0` |
| provider-keycloak | `v2.21.1` |
| function-python | `v0.5.0` |
| function-auto-ready | `v0.6.8` |

- **Educates installed with all CRDs in the cluster** for the Educates runtime.
  Install it through the upstream [Educates Installation Instructions](https://docs.educates.dev/en/stable/installation-guides/installation-instructions.html), [CLI flow](https://docs.educates.dev/en/stable/installation-guides/cli-based-installation.html), or [Carvel flow](https://docs.educates.dev/en/stable/installation-guides/carvel-based-installation.html). For Kustomize/Flux-based platform installs, Versioneer also publishes a vendored Educates base in [`versioneer-tech/bases`](https://github.com/versioneer-tech/bases), overlay [`educates/default`](https://github.com/versioneer-tech/bases/tree/main/educates/default), as `oci://ghcr.io/versioneer-tech/bases:educates-<sha12>`.
  Use the latest Versioneer Educates install from `versioneer-tech/bases` and
  follow the prerequisites of that installation.
  Its controllers need `get`, `list`, and `watch` access to CRD definitions
  for discovery at startup.
- **Crunchy PostgreSQL Operator installed** if you plan to use `spec.databases` (Postgres feature).
  Baseline: PGO `v6.0.x`, which serves `PostgresCluster` as `postgres-operator.crunchydata.com/v1`.
- **A Gateway API implementation with `TLSRoute` v1 support** if PostgreSQL should be exposed externally through `EnvironmentConfig.data.database.tlsRoute`.
  Use a Layer-4 capable controller such as Envoy Gateway, or your cluster-validated equivalent. The bundled Gateway API `v1.5.1` CRDs serve `TLSRoute` as `gateway.networking.k8s.io/v1`.
- **MongoDB Kubernetes Operator installed** if you plan to use `spec.documentStores` (document store feature).
  Tested baseline: MongoDB Kubernetes Operator chart `1.12.0`, which serves
  `MongoDBCommunity` as `mongodbcommunity.mongodb.com/v1` and accepts the CR
  fields emitted by this composition.
  The operator installation must provide its own controller RBAC; `provider-datalab` only creates namespace-local Mongo prerequisites such as service accounts, a Role, and an appdb RoleBinding inside the tenant namespace.
- **Redis Kubernetes Operator installed** if you plan to use `spec.cacheStores` (cache store feature).
  Tested baseline: Redis Operator chart `0.26.1`, with operator `0.26.0`. It
  serves `Redis` as `redis.redis.opstreelabs.in/v1beta2` and accepts the CR
  fields emitted by this composition.
- **Qdrant Kubernetes Operator installed** if you plan to use `spec.vectorStores` (vector store feature).
  Tested baseline: Qdrant Operator `0.0.3`, which serves `QdrantCluster` as
  `qdrant.io/v1alpha1`. Do not use the newer development line without changing
  the composition because that line uses a different API group.

Without the corresponding optional database operators installed, `spec.databases`, `spec.documentStores`, `spec.cacheStores`, and/or `spec.vectorStores` cannot reconcile.

For each optional service, configure storage classes, backup and restore, monitoring, upgrades, deletion, and who may request it.

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

Provider dependencies enable management of Helm, Kubernetes, and Keycloak resources:

- [00-mrap.yaml](https://github.com/versioneer-tech/provider-datalab/blob/main/educates/dependencies/00-mrap.yaml) – Activate Educates-specific Managed Resources.
- [01-deploymentRuntimeConfigs.yaml](https://github.com/versioneer-tech/provider-datalab/blob/main/educates/dependencies/01-deploymentRuntimeConfigs.yaml) – Runtime configs for providers/functions.
- [02-providers.yaml](https://github.com/versioneer-tech/provider-datalab/blob/main/educates/dependencies/02-providers.yaml) – Install Helm, Kubernetes, and Keycloak providers.
- [03-providerConfigs.yaml](https://github.com/versioneer-tech/provider-datalab/blob/main/educates/dependencies/03-providerConfigs.yaml) – **Apply in your target namespace** (e.g., `workspace`); sets up storage and identity configs.
- [functions.yaml](https://github.com/versioneer-tech/provider-datalab/blob/main/educates/dependencies/functions.yaml) – Functions used by compositions.
- [rbac.yaml](https://github.com/versioneer-tech/provider-datalab/blob/main/educates/dependencies/rbac.yaml) – RBAC for `provider-kubernetes`.

The supplied runtime configs apply the `RuntimeDefault` seccomp profile to provider and function Pods. They also prevent privilege escalation and remove all Linux capabilities from package runtime containers.

Recommended Crossplane dependency set for `datalab-educates`:

- Providers:
  - `provider-kubernetes` `v1.3.1` (`xpkg.upbound.io/crossplane-contrib/provider-kubernetes`)
  - `provider-helm` `v1.0.0` (`xpkg.upbound.io/crossplane-contrib/provider-helm`)
  - `provider-keycloak` `v2.21.1` (`ghcr.io/crossplane-contrib/provider-keycloak`)
- Functions:
  - `crossplane-contrib-function-python` `v0.5.0`
  - `crossplane-contrib-function-auto-ready` `v0.6.8`

Pin exact provider and function versions or digests in your GitOps source and upgrade them intentionally after validation.

For each Datalab, the composition provisions the workspace client, groups, roles, role bindings, service-account role binding, and memberships.

Set the target Keycloak realm with `EnvironmentConfig.data.iam.realm`. The `provider-keycloak` `ProviderConfig` must point at a reachable Keycloak instance with permissions to manage clients, client service-account roles, groups, group memberships, roles, role mappers, and protocol mappers in that realm. Users listed in `spec.users` must already exist in that realm. Shared browser ingress can use a central platform OAuth client, while direct OIDC integrations for a service owned by one Datalab can reuse the generated Datalab client because the composition includes redirect and web-origin entries for declared session hosts.

Each generated Datalab client is confidential. Provider Datalab publishes credentials in the runtime workshop namespace as `<datalab>-oauth2-client`, with data keys `client_id` and `client_secret`. Treat that runtime Secret as a workspace machine credential: namespace users who may create automation tokens can read it, and operators should rotate or revoke it when that trust boundary changes. Use it for client-credentials automation or for direct per-Datalab service protection, not as a default shared browser-ingress credential.

The generated roles are intentionally separated. Users get `ws_access` through the Datalab group, selected administrators get `ws_admin` through the admin group, and the generated client service account gets only `ws_api`. Extra token audiences are opt-in: when `EnvironmentConfig.data.iam.extraAudiences` is set, tokens issued by generated Datalab clients include those audience values. Any service or gateway that requires such an audience must use the same configured value and its OAuth client must emit it. Client-credentials tokens therefore identify machine automation and must not be accepted as browser-user tokens by ingress or application policy.

A Datalab creates the selected runtime, one shared `package-r` Data service,
and any requested managed services. It also supplies object-storage
credentials to the runtime. Complete IAM and ingress settings add a permanent
OAuth-protected Data endpoint.

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

Provide cluster-specific settings through an `EnvironmentConfig`. This is the operator-owned policy surface for an environment: it defines where ingress terminates, which storage endpoint is trusted, which storage classes may be used, and what the default security posture is.

```yaml
apiVersion: apiextensions.crossplane.io/v1beta1
kind: EnvironmentConfig
metadata:
  name: datalab
data:
  iam:
    realm: demo
    issuerURL: https://identity.acme.org/realms/demo
    internalURL: http://identity.identity-system.svc/realms/demo
  ingress:
    enabled: true
    class: nginx
    domain: datalab.acme.org
    secret: wildcard-tls
    annotations: {}
  storage:
    endpoint: https://s3.demo
    provider: Other
    region: demo
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
    overallQuota:
      storage: 100Gi
    security:
      externalEgress: true
```

The default `EnvironmentConfig` name is `datalab`. To use a different one for a specific `Datalab`, set `datalabs.pkg.internal/environment` as an annotation or label on that `Datalab`.

`ingress.enabled` and `httpRoute.enabled` default to `false`, which gives each
session an Educates-authenticated Data ingress. Enable one for a permanent
OAuth-protected Data endpoint per Datalab. Enabling both stops reconciliation.
Both require `iam.issuerURL`, `iam.internalURL`, and `ingress.domain`.

- `ingress.enabled: true` creates a Kubernetes Ingress. It requires
  `ingress.class` and `ingress.secret`. Use `ingress.annotations` for controller
  settings.
- `httpRoute.enabled: true` creates an HTTPS HTTPRoute and an HTTP-to-HTTPS
  redirect HTTPRoute. It requires an installed Gateway API controller and an
  existing Gateway with HTTP and TLS-terminating HTTPS listeners. The Gateway
  manages the certificate and must accept routes from Datalab runtime namespaces.

For HTTPRoute exposure, merge this block into the EnvironmentConfig:

```yaml
data:
  ingress:
    enabled: false
    class: nginx
    domain: lab.example.org
    secret: wildcard-tls
  httpRoute:
    enabled: true
    enableS3: true            # Experimental read-only S3 endpoint
    parentName: default
    parentNamespace: gateway-system
    sectionName: workspaces-https
    httpSectionName: workspaces-http
```

`httpRoute.enableS3` defaults to `false`. Set it to `true` to add the read-only
S3 endpoint for every Data-enabled Datalab in the environment. It requires
`httpRoute.enabled: true`. Browser and S3 requests use the same hostname.
There is no per-Datalab override. A Datalab with `spec.data.enabled: false`
creates neither service.

Missing required values stop reconciliation and appear in the Datalab status.
HTTPRoute exposure uses `ingress.domain` for the shared hostname. Keep
`ingress.class`, `ingress.secret`, and `ingress.annotations` for Educates
session Ingress objects; the permanent HTTPRoute uses Gateway-managed TLS.

Use `storage.forcePathStyle` for S3 path-style access and `database.tlsRoute`
for PostgreSQL Gateway listener references.

`storage.endpoint` identifies the S3 endpoint for session tools, cluster tools,
and `package-r`. The browser uses the permanent Data ingress and does not need
direct access to the S3 endpoint.

`storageClasses.allowed` is an optional allowlist for durable session PVCs. If it is set, Provider Datalab uses a requested StorageClass only when it is listed there; otherwise it falls back to the first entry. If the list is omitted or empty, any requested StorageClass is allowed.

`defaults.overallQuota.storage` sets the default aggregate PVC
requested-storage quota for each Datalab environment namespace. A Datalab can
override it with `spec.overallQuota.storage`; when both fields are omitted, the
hard default is `100Gi`. This quota does not include PVCs in other namespaces.

The `serviceCIDR` defines the internal Service network range expected by the vCluster’s API server. In the Datalab setup, the host cluster’s DNS and networking are reused, and no separate CoreDNS is deployed inside the vCluster. Using the host’s `serviceCIDR` therefore reduces startup time and control-plane overhead, since CoreDNS doesn’t need to start separately within each vCluster.

To find the correct value, use the same `serviceCIDR` as your host cluster — it’s typically visible in your cluster configuration or can be inferred by checking CoreDNS’s Service IP via `kubectl get svc kube-dns -n kube-system`.

Set `podCIDRs` to the host cluster Pod network ranges. Provider Datalab excludes
`podCIDRs` and `serviceCIDR` from broad generated external egress so traffic to
other runtime namespaces stays blocked unless you add an explicit
operator-owned NetworkPolicy.

For backend Pods in other namespaces that should be reachable by name, add an
explicit `internalEgress` entry. A MinIO backend in the `minio` namespace can
be modeled like this:

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

That renders an operator-owned `allow-internal-egress` NetworkPolicy alongside
`allow-namespace-egress` and the external egress policy path.

Direct S3 requests from `package-r` follow the same Datalab network policy. Use
`internalEgress` for an object-store Pod in another namespace. For an external
S3 address, enable external egress and include the required destination CIDR.
Browser requests go to the OAuth-protected Data ingress. They do not connect
to S3 directly.

If you only have `kubectl`, you can usually read `podCIDRs` from the nodes:

```bash
kubectl get nodes -o jsonpath='{range .items[*]}{.metadata.name}{"  "}{.spec.podCIDR}{"  "}{.spec.podCIDRs}{"\n"}{end}'
```

If a node has one or more Pod CIDR values, those are the ranges to configure.
`serviceCIDR` is usually not exposed as a first-class Kubernetes API field, so
the reliable sources are the control-plane configuration (`--service-cluster-ip-range`)
or your cluster bootstrap documentation. A `kube-dns` or `coredns` Service IP can
confirm the range, but it cannot reliably reveal the full CIDR on its own.

Provider Datalab asks for explicit CIDRs because Kubernetes NetworkPolicy
matches IP blocks, not a portable "cluster internal" label. The actual Pod and
Service ranges vary across clusters, CNIs, and IPv4/IPv6 setups, so the operator
has to provide the values that represent the local cluster topology.

`network.externalEgressCIDRs` is the external egress allowlist used when
`externalEgress` is true. Use `0.0.0.0/0` and `::/0` for open external
IPv4/IPv6 egress, or narrower operator-approved CIDRs for restricted
environments. `externalEgress` defaults to `true`, but if
`externalEgressCIDRs` is empty or omitted, Provider Datalab does not render a
broad external egress allow block.

`network.blacklistIPs` lists CIDRs excluded from broad generated external
egress, such as cloud metadata endpoints. Provider Datalab always renders
`deny-egress` and `allow-namespace-egress` unless their names are listed in
`network.excludePolicies`. When a Datalab enables a vCluster, it also renders
`allow-vcluster-egress`. This policy permits TCP ports 443 and 8443 only to
that Datalab's vCluster control-plane Pods. Provider Datalab renders
`allow-dns-egress` when `externalEgress`, the vCluster, or Data is enabled. It
renders
`allow-external-egress` only when `externalEgress` is true. Use
`excludePolicies` only when another policy system
supplies equivalent controls. Excluding `allow-dns-egress` also suppresses the
Datalab-owned `package-r-dns` policy.

If external access is generally granted at the platform level, you can still restrict it for specific teams or workspaces. See [Sandbox Security Measures](../security/sandbox-controls.md) for the policy details, including how `externalEgress: false` removes broad external egress while retaining namespace-local and vCluster API access. DNS remains enabled when a vCluster or Data needs service-name resolution.

Apply dependency manifests in order so that later objects can reference earlier ones cleanly: MRAP first, then deployment runtime configs, providers, namespaced provider configs, functions, and finally RBAC. After each dependency stage, wait for the corresponding `ProviderRevision` or `FunctionRevision` to become healthy before moving on.

Manage provider credentials and storage secrets through your normal secret-management path, such as External Secrets or Sealed Secrets, rather than committing live credentials into Git. If you use [Provider Storage](https://provider-storage.versioneer.at/), let it create the bucket and credentials, then reference those credentials from the `Datalab`. This keeps credential issuance, rotation, and revocation auditable outside the workspace session.

---

## Step 4 – Storage credentials

Provider Datalab does not create object-storage buckets. Create the bucket and credentials manually, through your platform process, or with [Provider Storage](https://provider-storage.versioneer.at/).

The `storage` section in the `EnvironmentConfig` tells Provider Datalab where to read the credentials. The composition reads the Secret named by `spec.secretName`, or the `Datalab` name when `spec.secretName` is omitted. This Secret must exist in `storage.secretNamespace` and include at least:

- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`

The S3 identity must permit bucket listing with AWS `s3:ListAllMyBuckets`.

`package-r` uses these credentials for direct S3 access. The configured
`storage.endpoint` must be reachable from the `package-r` Pod and support
path-style S3 addresses.

Create it manually, for example:

```bash
kubectl -n datalab create secret generic demo \
  --from-literal=AWS_ACCESS_KEY_ID=<KEY_ID> \
  --from-literal=AWS_SECRET_ACCESS_KEY=<SECRET>
```

## Step 5 – Create a Datalab

For optional S3 setup and client configuration, see
[S3 client access](usage_concepts.md#s3-client-access).

The example below creates a lab for one user with one session. The installed package and `EnvironmentConfig` supply the shared settings.

- Sessions present -> each declared session gets a workspace PVC; sessions default to `state: started`.
- `state: started` -> runtime created; `state: stopped` -> PVC retained without runtime.
- No sessions -> no declared session PVC or runtime is pre-created.
- Files present -> workshop tab enabled; none -> no workshop tab.
- `spec.vcluster: true` -> vcluster provisioned; `false` -> namespace-scoped runtime.
- `spec.data.enabled` creates or omits the shared service, Data tabs, and Data
  ingress.
- The effective `spec.data.enabled` value cannot change after creation.
- `spec.data.readOnlyMount` selects read-only or write application permissions.
  S3 IAM takes precedence.

With the permanent Data address enabled, users can share files with anyone by
putting them in the Datalab's `public` folder. Readers do not need to sign in.
See [Sharing Data with the World](usage_concepts.md#sharing-data-with-the-world)
for the folder location and an example.

```yaml
apiVersion: pkg.internal/v1beta2
kind: Datalab
metadata:
  name: demo
  namespace: datalab
spec:
  users:
  - alice
  sessions:
  - name: default
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
kubectl api-resources --api-group=gateway.networking.k8s.io
kubectl api-resources --api-group=mongodbcommunity.mongodb.com
kubectl api-resources --api-group=redis.redis.opstreelabs.in
kubectl api-resources --api-group=qdrant.io

kubectl get managedresourcedefinitions | grep -E 'helm|kubernetes|keycloak'

kubectl get xrd
kubectl get datalabs.pkg.internal -A
```
