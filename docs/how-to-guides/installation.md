# Provider Datalab – Installation Guide

The `provider-datalab` configuration package lets platform operators expose **collaborative data labs** on Kubernetes as a PaaS-style building block. Labs, sessions, storage access, identity, and optional managed services are declared through one namespaced `Datalab` spec. The operator still owns the backing services, policies, and backup model.

---

## Namespacing Model (Important)

Everything in this guide is **namespaced**:

- You **apply** `Datalab` claims **to a namespace** (e.g., `workspace`).
- The **referenced Secret for storage** lives in the namespace configured by `EnvironmentConfig.data.storage.secretNamespace`, normally the same namespace as the `Datalab` claim. The Secret name is `spec.secretName`, or the `Datalab` name when `spec.secretName` is omitted.
- Any **namespaced ProviderConfigs** or supporting objects that the compositions depend on **must exist in that same target namespace** (e.g., `workspace`).

> In short: choose your target namespace (e.g., `workspace`), apply the provider configs there, create or provision the referenced object-storage credentials there, and create your `Datalab` claims in that namespace.

---

## Prerequisites

Before installing Provider Datalab, decide which parts of the service catalogue the platform will offer. The base runtime needs Crossplane, Educates, an enforcing CNI, and the platform ingress/identity/storage path. Optional database and store fields should only be enabled when the corresponding operators, backup model, and lifecycle ownership are ready.

- A running Kubernetes cluster (e.g., `kind`, managed K8s).
- `kubectl` access.
- **A CNI that enforces Kubernetes NetworkPolicy**. The generated Datalab policies are useful only when the dataplane enforces them.
- **Kyverno** installed in the cluster. Provider Datalab uses Kyverno policies to enforce platform guardrails for generated workloads and sandbox resources.
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

- **Educates installed with all CRDs in the cluster** for the Educates runtime.
  Install it through the upstream [Educates Installation Instructions](https://docs.educates.dev/en/stable/installation-guides/installation-instructions.html), [CLI flow](https://docs.educates.dev/en/stable/installation-guides/cli-based-installation.html), or [Carvel flow](https://docs.educates.dev/en/stable/installation-guides/carvel-based-installation.html). For Kustomize/Flux-based platform installs, Versioneer also publishes a vendored Educates base in [`versioneer-tech/bases`](https://github.com/versioneer-tech/bases), overlay [`educates/default`](https://github.com/versioneer-tech/bases/tree/main/educates/default), as `oci://ghcr.io/versioneer-tech/bases:educates-<sha12>`.
  Use the latest Versioneer Educates install from `versioneer-tech/bases`; the current install requires Kyverno.
- **Crunchy PostgreSQL Operator installed** if you plan to use `spec.databases` (Postgres feature).
  Baseline: PGO `v6.0.x`, which serves `PostgresCluster` as `postgres-operator.crunchydata.com/v1`.
- **A Gateway API implementation with `TLSRoute` v1 support** if PostgreSQL should be exposed externally through `EnvironmentConfig.data.database.gateway`.
  Use a Layer-4 capable controller such as Envoy Gateway, or your cluster-validated equivalent. The bundled Gateway API `v1.5.1` CRDs serve `TLSRoute` as `gateway.networking.k8s.io/v1`.
- **MongoDB Kubernetes Operator installed** if you plan to use `spec.documentStores` (document store feature).
  Suggested tested line: MongoDB Operator `v1.7.x` (or your cluster-validated equivalent).
  The operator installation must provide its own controller RBAC; `provider-datalab` only creates namespace-local Mongo prerequisites such as service accounts, a Role, and an appdb RoleBinding inside the tenant namespace.
- **Redis Kubernetes Operator installed** if you plan to use `spec.cacheStores` (cache store feature).
  Suggested tested line: Redis Operator `v0.21.x` (or your cluster-validated equivalent).
- **Qdrant Kubernetes Operator installed** if you plan to use `spec.vectorStores` (vector store feature).
  Suggested tested line: Qdrant Operator `v1.15.x` (or your cluster-validated equivalent).

Without the corresponding optional database operators installed, `spec.databases`, `spec.documentStores`, `spec.cacheStores`, and/or `spec.vectorStores` cannot reconcile.

Treat these optional operators as platform service classes. If you enable a field in the `Datalab` API, make sure the operations model is ready too: storage classes, backup and restore, monitoring, upgrades, tenant lifecycle, and who may request the service.

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

Provider dependencies activate Helm, Kubernetes, and Keycloak resources as needed:

- [00-mrap.yaml](https://github.com/versioneer-tech/provider-datalab/blob/main/educates/dependencies/00-mrap.yaml) – Activate Educates-specific Managed Resources.
- [01-deploymentRuntimeConfigs.yaml](https://github.com/versioneer-tech/provider-datalab/blob/main/educates/dependencies/01-deploymentRuntimeConfigs.yaml) – Runtime configs for providers/functions.
- [02-providers.yaml](https://github.com/versioneer-tech/provider-datalab/blob/main/educates/dependencies/02-providers.yaml) – Install Helm, Kubernetes, and Keycloak providers.
- [03-providerConfigs.yaml](https://github.com/versioneer-tech/provider-datalab/blob/main/educates/dependencies/03-providerConfigs.yaml) – **Apply in your target namespace** (e.g., `workspace`); sets up storage and identity configs.
- [functions.yaml](https://github.com/versioneer-tech/provider-datalab/blob/main/educates/dependencies/functions.yaml) – Functions used by compositions.
- [rbac.yaml](https://github.com/versioneer-tech/provider-datalab/blob/main/educates/dependencies/rbac.yaml) – RBAC for `provider-kubernetes`.

Recommended Crossplane dependency set for `datalab-educates`:
- Providers:
  - `provider-kubernetes` (`xpkg.upbound.io/crossplane-contrib/provider-kubernetes`)
  - `provider-helm` (`xpkg.upbound.io/crossplane-contrib/provider-helm`)
  - `provider-keycloak` (`ghcr.io/crossplane-contrib/provider-keycloak`)
- Functions:
  - `crossplane-contrib-function-python`
  - `crossplane-contrib-function-auto-ready`

Pin exact provider and function versions or digests in your GitOps source and upgrade them intentionally after validation.

Keycloak-managed access is supported: the composition automatically provisions the workspace client, groups, roles, role bindings, service-account role binding, and memberships. At the same time, the provider is intentionally only a workspace provisioning building block. In many production deployments it is better to delegate authentication to the platform, for example to NGINX Ingress with `oauth2-proxy` or APISIX with the `openid-connect` plugin, while keeping `auth.type = delegated` in the Datalab environment configuration.

When Keycloak-managed access is used, the target realm is configured with `EnvironmentConfig.data.iam.realm`, and the `provider-keycloak` `ProviderConfig` must point at a reachable Keycloak instance with permissions to manage clients, client service-account roles, groups, group memberships, roles, role mappers, and protocol mappers in that realm. Users accessing a workspace do not necessarily have to exist in Keycloak when authentication is delegated to another platform component. Direct OIDC ingress integrations can still reuse the Datalab-generated Keycloak client because the composition includes redirect and web-origin entries for declared session hosts.

Each generated Datalab client is confidential. Provider Datalab publishes the credentials for ingress controllers and client-credentials automation in the runtime workshop namespace as `<datalab>-oauth2-client`, with data keys `client_id` and `client_secret`. Treat that runtime Secret as a workspace machine credential: namespace users who may create automation tokens can read it, and operators should rotate or revoke it when that trust boundary changes.

The generated roles are intentionally separated. Users get `ws_access` through the Datalab group, selected administrators get `ws_admin` through the admin group, and the generated client service account gets only `ws_api`. Extra token audiences are opt-in: when `EnvironmentConfig.data.iam.extraAudiences` is set, tokens issued by generated workspace clients include those audience values. The Workspace API gateway and central Workspace API OAuth client must use the same configured audience value; configure the central client with an equivalent audience mapper in the realm or platform identity setup. Client-credentials tokens therefore identify machine/API automation and must not be accepted as browser-user tokens by ingress or application policy.

When installed, a Datalab will provision a vcluster (if enabled), launch the Educates tooling stack (VS Code Server, terminal, storage browser, plus tools like `awscli` and `rclone`), wire in object-storage credentials, and reconcile any requested platform-managed data services.

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

Provide cluster-specific settings through an `EnvironmentConfig`. This is the operator-owned policy surface for an environment: it defines where ingress terminates, how authentication is handled, which storage endpoint is trusted, which storage classes may be used, and what the default security posture is.

```yaml
apiVersion: apiextensions.crossplane.io/v1beta1
kind: EnvironmentConfig
metadata:
  name: datalab
data:
  iam:
    realm: demo
  auth:
    # Use "credentials" to reuse storage credentials, or "delegated" when
    # the ingress/platform layer handles authentication.
    type: delegated
  ingress:
    class: nginx
    domain: datalab.acme.org
    secret: wildcard-tls
  storage:
    endpoint: https://s3.demo
    provider: Other
    region: demo
    force_path_style: "true"
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
    security:
      externalEgress: true
```

The default `EnvironmentConfig` name is `datalab`. To use a different one for a specific `Datalab`, set `datalabs.pkg.internal/environment` as an annotation or label on that `Datalab`.

`storageClasses.allowed` is an optional allowlist for durable session PVCs. If it is set, Provider Datalab uses a requested StorageClass only when it is listed there; otherwise it falls back to the first entry. If the list is omitted or empty, any requested StorageClass is allowed.

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
`network.excludePolicies`. It renders `allow-dns-egress` and
`allow-external-egress` only when `externalEgress` is true. Use
`excludePolicies` only as an operator escape hatch when another policy system
supplies equivalent controls.

If external access is generally granted at the platform level, you can still restrict it for specific teams or workspaces. See [Sandbox Security Measures](../security/sandbox-controls.md) for the policy details, including how `externalEgress: false` removes the DNS and broad external egress policies so only internal access remains.

Apply dependency manifests in order so that later objects can reference earlier ones cleanly: MRAP first, then deployment runtime configs, providers, namespaced provider configs, functions, and finally RBAC. After each dependency stage, wait for the corresponding `ProviderRevision` or `FunctionRevision` to become healthy before moving on.

Manage provider credentials and storage secrets through your normal secret-management path, such as External Secrets or Sealed Secrets, rather than committing live credentials into Git. If you use [Provider Storage](https://provider-storage.versioneer.at/), let it create the bucket and credentials, then reference those credentials from the `Datalab`. This keeps credential issuance, rotation, and revocation auditable outside the workspace session.

---

## Step 4 – Storage credentials

Provider Datalab does not create object-storage buckets. Create the bucket and credentials manually, through your platform process, or with [Provider Storage](https://provider-storage.versioneer.at/).

The `storage` section in the `EnvironmentConfig` tells Provider Datalab where to read the credentials. The composition reads the Secret named by `spec.secretName`, or the `Datalab` name when `spec.secretName` is omitted. This Secret must exist in `storage.secretNamespace` and include at least:

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

The minimal example creates a user-scoped lab with one session. From an operator view, this is the tenant request; whether it is allowed, which defaults apply, and which backing services exist are controlled by the installed package and `EnvironmentConfig`.
- Sessions present -> each declared session gets a workspace PVC; sessions default to `state: started`.
- `state: started` -> runtime created; `state: stopped` -> PVC retained without runtime.
- No sessions -> no declared session PVC or runtime is pre-created.
- Files present -> workshop tab enabled; none -> no workshop tab.
- `spec.vcluster: true` -> vcluster provisioned; `false` -> namespace-scoped runtime.

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
