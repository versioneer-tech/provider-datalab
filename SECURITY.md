# Security

A virtual API uses caller token roles and Kubernetes RBAC. A downloaded
profile selects an endpoint and namespace; it grants no access. Virtual
workloads can use the credentials, volumes, permissions, and
network access available to their Pods.

The platform operator sets the
[EnvironmentConfig](docs/how-to-guides/installation.md#environmentconfig-values-and-defaults)
and decides who can use these resources. The host cluster must enforce network
policies, admission rules, Pod security, and RBAC. Virtual clusters share its
nodes and kernel.

Registry, MongoDB, and Redis passwords are derived from resource names and are
predictable. Keep their endpoints within the approved team network boundary.

| Control | Details |
| --- | --- |
| Caller roles, public profiles, and virtual RBAC | [Virtual API access](docs/how-to-guides/vcluster.md#api-access) |
| Browser sign-in, Datalab roles, and machine tokens | [Authentication](docs/how-to-guides/authentication.md) |
| Service credentials and token exchange callers | [Credential access](#credential-access), [Token exchange callers](#token-exchange-callers) |
| Pod credentials, Kubernetes access, and privileged workloads | [Workload access](#workload-access) |
| Allowed traffic and generated NetworkPolicies | [Network policies](#network-policies) |
| Files that readers can open without sign-in | [Public sharing](docs/how-to-guides/usage_concepts.md#sharing-data-with-the-world) |

The platform team also manages node access, DNS, storage classes, quotas,
cloud IAM, backup, retention, and audit. Check these controls together before
giving users access to a Datalab.

## Credential access

Restrict read access to Secrets and provider Object resources. Object specs can
contain credentials; status redaction does not remove them from specs or
annotations. The supplied provider-kubernetes runtime uses `--sanitize-secrets`.
Crossplane reads source Secrets directly through its required-resource API.

PostgreSQL connections use the administrative `postgres` account. Create
application accounts and grants for workloads that need less access.
A virtual administrator can read all Secrets in that virtual cluster. A user
who can create Pods in a namespace can usually mount that namespace's Secrets.

The Datalab OAuth client secret permits service-account token requests. Give it
only to authorized callers. The service account has `ws_api` by default.
See [credential Secrets](docs/how-to-guides/authentication.md#credential-secrets-and-machine-access)
for source and runtime copies.

## Identity prerequisites

Use Keycloak 26.8.1 or later with Standard Token Exchange V2 and client policies
enabled. Default identity scopes must contain no role grants or role mappers.
Enable the `grant-type`, `client-scopes`, and `reject-request` client-policy
providers and the built-in Role Name and Realm Roles protocol mappers.

The realm must permit the `offline_access` scope and role for CLI device login.
See [Authentication](docs/how-to-guides/authentication.md) for generated roles,
scopes, and login flows.

## Token exchange callers

A service that exchanges tokens for users must:

- Accept full profile scope names, or add the Datalab name to short names.
- Permit only configured additional profiles and check each requested role
  against the caller's validated token.
- Use the original caller access token as `subject_token` and authenticate
  with the Datalab client credentials.
- Check the returned signature, validity, issuer, audiences, subject, requested
  roles, and absence of unexpected permissions.
- Reject missing roles even when the token endpoint returns success.
- Check that the caller may request token issuance through that service.

## Token revocation

Virtual APIs validate JWTs locally. Issued tokens can remain usable until
expiry after role removal, logout, or client-secret rotation. Keycloak also
[keeps exchanged tokens valid after their source token is revoked](https://www.keycloak.org/securing-apps/token-exchange#_revocation).

To stop a profile's access before token expiry, remove its configuration or
required Kubernetes RBAC binding through the source configuration. After
reconciliation, this denies all callers that use the profile. Revoke the user's
offline session in Keycloak to stop further CLI refresh; browser logout does
not end offline access.

| Action | Human device login | Delegated token |
| --- | --- | --- |
| Access token expires | Helper attempts refresh with the client secret. | Recipient must obtain a new token. |
| Offline session expires or is revoked | A new device login is needed. | An issued token can remain usable until `exp`. |
| Keycloak role is removed | New tokens lose the role; issued tokens can retain it. | An issued token can retain the role until `exp`. |
| Profile or required RBAC binding is removed | Access stops after reconciliation. | Access stops after reconciliation. |

## Workload access

Workloads created in a virtual cluster run as Pods in the host cluster. They
can use their mounted credentials, PVCs, and other volumes. Check these
permissions together when deciding which code a user may run.

### Kubernetes access

Namespace profiles receive `view`, `edit`, or `admin` permissions through a
RoleBinding. Cluster administrator profiles use `namespace: "*"` and a
ClusterRoleBinding. Kubernetes RBAC enforces access; a context namespace is
only a client default. Downloaded profiles use caller tokens. Keep the
provider's private recovery kubeconfig under operator control.

Application owners can install controllers and CRDs with virtual cluster
administration credentials. Their controllers use virtual ServiceAccounts.
Application installation does not require host cluster credentials. The
platform operator controls which host capabilities the virtual cluster exposes.

Clients can port-forward through the virtual API. RBAC controls
`pods/portforward` access, not individual port numbers. Reconnect when a Pod
stops or is replaced. Kubernetes authenticates this connection; direct Pod
traffic needs the application's own authentication when required.

### Platform boundary

The host service namespace is the team boundary across all virtual clusters
in a Datalab. Host Pod security, network policies, and resource quota apply to
synced workloads. Virtual namespaces do not create separate host networks.

Host mounts, runtime sockets, broad roles, and privileged containers can give
workload code access beyond its namespace. Grant only the access a workload
needs. Set application images, resource limits, security contexts, and token
mounting in the application package.

Virtual PVCs use only classes listed in
`EnvironmentConfig.data.volumes.storageClasses.allowed`. Host admission
enforces this list even if a virtual administrator creates another StorageClass.
Named Datalab volumes use the same allowlist. Their host backup identities are
separate from application credentials and virtual cluster syncers. See
[Volume backup access](#volume-backup-access) for their permissions.

### Volume bindings

The operator installs provider RBAC for host admission policies. A binding
creates static virtual PV and PVC records; vCluster does not sync these records
or allocate another volume. A host MutatingAdmissionPolicy directs Pod mounts
to the named host PVC. It matches the instance's syncer, virtual namespace, and
configured claim name. This requires host Kubernetes 1.36 or later.

Host admission denies syncer changes and deletion of every named host PVC,
including when no binding exists. Virtual admission preserves each bound
claim's control label, static PV reference, and policy owner. If a virtual PVC is replaced,
reconciliation updates the PV's claim UID so the replacement can bind.
The logical records belong to a virtual binding policy, with background
garbage collection. They have no ownership of the host PVC. This permits
virtual cluster removal even when a virtual PVC is still in use.

One named volume can bind to one virtual PVC. Removing a binding or virtual
cluster leaves its host PVC and backup schedule while the volume remains declared.

### Explain access to users

Tell users which data and services a workload can use, whether Kubernetes
and internet access are available, and whether privileged workloads are
allowed. Explain what survives replacement or deletion, what is backed up,
and who can restore it.

Stopping a Pod or tightening a network rule does not revoke a leaked
credential. Rotate or revoke it at its source. Protect the OAuth client Secret
as described in [Authentication](docs/how-to-guides/authentication.md#credential-secrets-and-machine-access).

## Network policies

Provider Datalab creates ingress and egress policies in the Datalab-named host
service namespace. This namespace is the team boundary. Services, virtual
control planes, and synced workload Pods use it regardless of their virtual
namespace. Virtual clusters in one Datalab share this boundary.
The cluster CNI must enforce Kubernetes NetworkPolicy for these rules to take
effect.

NetworkPolicies inside a virtual cluster are not synced to the host. Configure
team network access through EnvironmentConfig. The generated host policies
permit same-team traffic; they do not isolate workloads within a team.

### Generated namespace policies

| Policy | Created when | Allows |
| --- | --- | --- |
| `deny-ingress` | By default | No ingress by itself; service and explicit internal rules can allow traffic. |
| `allow-namespace-ingress` | By default | Traffic from Pods in the same host service namespace. |
| `deny-egress` | By default | No egress by itself; other policies can allow traffic. |
| `allow-namespace-egress` | By default | Traffic to Pods in the same runtime namespace. |
| `allow-dns-egress` | External egress, Data, registry, or vCluster is enabled | DNS to `kube-system` on TCP and UDP port 53. |
| `allow-external-egress` | External egress is enabled | The configured external CIDRs, minus excluded ranges. |
| `allow-internal-egress` | Internal targets are configured | The selected backend Pods and ports in other namespaces. |
| `allow-internal-ingress` | Internal sources are configured | The selected source Pods and ports from other namespaces. Target selectors can limit the receiving Pods. |

The DNS rule lets Data and the registry resolve storage hosts and lets
workloads resolve their vCluster Service. Same-namespace rules permit access
to the Datalab's virtual API.

NetworkPolicies are additive. `deny-egress` selects Pods for egress isolation;
it does not override an allow rule in another selected policy. Check all
policies that select a Pod when testing access.

### External and internal ranges

Supply the host Pod and Service CIDRs so that broad external egress does not
also grant access to other Datalab namespaces. The rule excludes these ranges
and the configured blacklist. Use explicit internal rules for required
backends in other namespaces. See [Network access](#network-access)
for setup examples and the [network reference](docs/how-to-guides/installation.md#network-rules)
for all fields.

With external egress disabled, same-namespace traffic, DNS needed by Data, registry, or
vCluster, and access to the Datalab's vCluster API remain allowed.
Standard NetworkPolicy cannot express ordered deny rules or DNS-name rules.

### Service policies

For internal access, packageR accepts port 8888 from Pods in the service namespace.
For permanent access, its OAuth proxy accepts port 4180. See
[Data and sharing](docs/how-to-guides/usage_concepts.md#data-and-sharing) for
browser access and public links.

The S3 service accepts Gateway traffic on port 8080. Data and S3 proxies can
reach IAM on TCP port 8080 in the configured IAM namespace. Object-storage
access follows the Datalab's egress rules. Set `iam.namespace` to the namespace
that contains the Keycloak Pods.

The registry accepts TCP port 5000. Its health port is not exposed by the
Service or public routes. Object-storage access uses the Datalab's egress rules.

Each virtual API accepts ingress on TCP port 8443 for authenticated Kubernetes
access through the Gateway. Its workload and DNS policies permit the required
control-plane traffic. These allowances add to the namespace policies.

Each named volume adds a policy for its host backup Job Pods. It permits DNS
and API traffic on TCP 443 and 6443. No source PVC is mounted in these Pods.

### Replace or exclude policies

Use `EnvironmentConfig.data.network.excludePolicies` only when another policy
system provides the required controls. Excluding `allow-dns-egress` also
suppresses the Data DNS policy.

Use RBAC and admission rules to limit who can change NetworkPolicies or
select privileged and admin settings.

## Network access

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
[Network policies](#network-policies) for how policies combine,
Data access, and policy exclusions.

## Volume backup access

`dependencies/rbac.yaml` installs the read-only ClusterRole
`datalab-volume-snapshot-classes`. Each backup identity can read snapshot class
metadata, read its source PVC, and create, read, list, and delete snapshots in
its Datalab namespace. It cannot delete PVCs or read Secrets. The provider can
observe snapshot classes and bind this operator-owned role, but cannot change
its rules. Provider Datalab grants no snapshot permissions to its virtual cluster
syncers.

The backup Pod's NetworkPolicy permits DNS and API traffic on TCP 443 and 6443.
The host CNI must allow this traffic to the selected API endpoint. The Job uses
its projected ServiceAccount token, with no external kubeconfig or source-volume
mount.

