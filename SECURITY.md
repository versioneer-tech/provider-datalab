# Security policy

## Report a vulnerability

Send private reports to `oss@versioneer.at`. Include the affected release or
commit, reproduction steps, expected and actual behavior, and possible impact.
Do not open a public issue or send credentials, private data, or complete
cluster logs. Maintainers coordinate a fix and disclosure with the reporter.
Response times depend on maintainer availability.

## Supported releases

Security fixes apply to the latest stable release of the `versioneer.at/v1` API.
Release candidates are for testing, not supported production use.

## Build and release checks

CI uses the [local check commands](README.md#checks). Branch rules must require
`required_checks`. Check jobs have read-only access; publication credentials
are limited to release and documentation jobs.

| Check | Coverage |
| --- | --- |
| File and documentation checks | Generated composition, copyright, strict docs, workflow syntax, and redacted secret scans of current files. Full Git history is not scanned. |
| Units and integration | Full units and all eight integration profiles for code changes. Draft PRs defer cluster tests. |
| Source dependencies | Production scans cover build, documentation, and security-tool Python locks. Full tests audit test dependencies and run source govulncheck on the Go admission module. |
| Configuration package | Saved package, source, and dependency inventories. |
| External images | Shipped service, provider/function, nested DNS, Crossplane, and CloudNativePG images on Linux AMD64. Test-only images are scanned when full tests run. |

### Dependency updates and tool installation

| Input | Update process |
| --- | --- |
| Actions and production/build Python dependencies | Weekly Dependabot PRs, with routine minor/patch updates grouped by ecosystem. |
| Production template image fields | Daily Dependabot PRs, including weekends. Current-image digest updates stay grouped. |
| Python image defaults and Crossplane `spec.package` references | The [daily image report](.github/workflows/image-updates.yaml) lists version and digest changes for manual updates. |
| Tool versions/checksums and `.go-version` | Manual review. The installer uses [scripts/tools.json](scripts/tools.json). |
| Test-only Python, Go, and images | Full tests report available updates and vulnerabilities on use. No scheduled version updates or production-release blocking. |

Docker majors appear in the daily report for separate manual PRs. Other
major updates get separate Dependabot PRs. Review, scan, and test updates;
do not apply audit fixes automatically. After template or composition edits,
regenerate `composition.yaml` and review affected render fixtures.

Shared runtime/test images remain in production scope. Secret checks cover
tests. Test dependency reports are advisory; review them before using fixtures.
Update versions deliberately and repeat the relevant checks. GitHub security
alerts are managed separately from scheduled version updates.

Actions use full SHAs, images use immutable digests, and Python requirements
use fixed hashes. See [dependency maintenance](README.md#maintain-dependencies)
for update commands.

### Local candidate checks

After [development setup](README.md#setup), install the scan tools and use a
new directory for each candidate. These commands preserve earlier reports and
use an empty registry configuration for public images:

```bash
python3 scripts/install-tools.py crane trivy
mkdir -p build
run_dir="$(mktemp -d "$PWD/build/candidate-check.XXXXXX")"
export DOCKER_CONFIG="$run_dir/registry"
mkdir -p "$DOCKER_CONFIG"
python3 scripts/security.py prepare --version 0.0.0-rc.1 \
  --commit "$(git rev-parse HEAD)" --candidate "$run_dir/candidate" --allow-dirty
python3 scripts/security.py scan --candidate "$run_dir/candidate" \
  --reports "$run_dir/reports" --allow-dirty
python3 scripts/security.py verify --candidate "$run_dir/candidate" \
  --reports "$run_dir/reports" --allow-dirty
```

Read `summary.md` for findings and errors. `--allow-dirty` is for local checks;
these candidates cannot be published.

### Candidate and publication

1. Prepare release notes with behavior changes and security fixes. Merge the
   changes with signed commits.
2. Wait for a full successful Tests run on the protected default branch for
   the exact release commit. PR and docs-only runs do not qualify. Use a full
   manual run for a docs-only release commit.
3. Create an unsigned annotated tag with Git, then push it. Tags have no `v`
   prefix: `git -c tag.gpgSign=false tag -a <version> <commit> -m <version>`.
4. Check the publication workflow, release assets, and versioned documentation.
   If scanning fails, assess the report before retrying.

For GPG signing, set `git config --local user.signingkey <full-key-fingerprint>`,
`git config --local commit.gpgsign true`, and
`git config --local tag.gpgsign false` on the computer that holds your key.
Register the public key with GitHub. See [commit signing](https://docs.github.com/en/authentication/managing-commit-signature-verification/signing-commits).
Verify the effective signed-commit rule separately.

Release assets include the package, source archive, security manifest,
external-image inventory, CycloneDX SBOMs, scan results, and checksums. Alpha,
beta, and RC releases are prereleases. Only stable releases advance `latest`.

### Scan policy

| Result | Effect |
| --- | --- |
| CRITICAL, with or without a fix | Block unless an active image exception applies |
| HIGH with a fix | Block unless an active image exception applies |
| HIGH without a fix | Report separately; acceptance needs an owner, reason, mitigation where possible, and review date |
| MEDIUM, LOW, UNKNOWN | Retain in reports |
| Unsupported image OS, scanner failure, or missing inventory/report/SBOM | Block |

Production native audit failures and secret findings also block publication.
Maintainers must assess failed daily scans.

### Temporary vulnerability exceptions

The [exception policy](scripts/vulnerability-exceptions.json) lists accepted
image digests, the owner, reason, mitigation, and expiry. Acceptance covers
findings discovered in those images before expiry. Maintainers must review
exceptions before renewal. Acceptance does not fix vulnerable packages.

### Daily scans and retention

Daily scans cover the latest stable release and the newest RC for a newer
version. Without a stable release, they cover the newest RC. Manual runs can
select older published tags.

Candidates are retained for seven days; reports and SBOMs for 90 days, including
failed scans. Release assets keep the inventories and scan results.

### Coverage and verification limits

Inventories cover the package and selected Linux AMD64 images. Coverage excludes
operator overrides, disabled optional vCluster components, host software, Go
build-tool modules, and native libraries bundled in build/test wheels.

Scan the platform's actual identity, Gateway, CNI, CSI, and object-storage images
separately. Test fixtures do not verify those deployments.

## Deployment boundary

A virtual API uses caller token roles and Kubernetes RBAC. A downloaded
profile selects an endpoint and namespace; it grants no access. Virtual
workloads can use the credentials, volumes, permissions, and
network access available to their Pods.

The platform operator sets the
[EnvironmentConfig](docs/how-to-guides/installation.md#environmentconfig-values-and-defaults)
and decides who can use these resources. The host cluster must enforce network
policies, admission rules, Pod security, and RBAC. Virtual clusters share its
nodes and kernel.

Registry and Valkey passwords are random and stored in native Secrets.
Reconciliation retains existing values. Keep service endpoints within the
approved team network boundary.

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
CloudNativePG generates the administrative password. Datalab user passwords
use that private entropy when first created and are stored in separate Secrets.
Reconciliation and administrative password rotation retain existing user
passwords. Named-user Secrets grant login access; application setup owns
database grants and schemas.
A virtual administrator can read all Secrets in that virtual cluster. A user
who can create Pods in a namespace can usually mount that namespace's Secrets.

The Datalab OAuth client secret permits service-account token requests. Give it
only to authorized callers. The service account has `ws_api` by default.
See [credential Secrets](docs/how-to-guides/authentication.md#credential-secrets-and-machine-access)
for source and runtime copies.

Managed store names share the credentials of their service instance. Valkey key
prefixes organize data; they do not restrict access. Clients must add the prefix
to their keys. Use separate service instances when applications need separate
credentials and data volumes.

## Identity prerequisites

Use Keycloak 26.8.1 or later with Standard Token Exchange V2 and client policies
enabled. Default identity scopes must contain no role grants or role mappers.
Enable the `grant-type`, `client-scopes`, and `reject-request` client-policy
providers and the built-in Role Name and Realm Roles protocol mappers.

The realm must permit the `offline_access` scope and role for CLI device login.
See [Authentication](docs/how-to-guides/authentication.md) for generated roles,
scopes, and login flows.

## Login clients

Check OAuth state, use PKCE, and authenticate the confidential client when
redeeming an authorization code. Request only the scopes the application needs.
See [Authentication](docs/how-to-guides/authentication.md#oauth-scopes-and-direct-login)
for request parameters.

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

## PostgreSQL snapshot access

Install the [snapshot prerequisites](docs/how-to-guides/installation.md#volume-snapshots)
before enabling PostgreSQL backups. CloudNativePG needs permission to create
and manage its database snapshots. Crossplane's Kubernetes provider observes
the selected snapshot class and checks its `Delete` policy.

PostgreSQL uses a native CloudNativePG `ScheduledBackup`, with no custom backup
Job or ServiceAccount. The default is a cold snapshot daily at 01:00 UTC.
`database.schedule` uses CNPG's six-field cron format, including seconds.
The only database instance stops reads and writes during capture. See the
[CNPG backup documentation](https://cloudnative-pg.io/docs/1.30/backup/).

CloudNativePG makes the Cluster the owner of each Backup and makes the Backup
the owner of its VolumeSnapshots. Deleting a Backup removes its snapshots.
Disabling backups removes the schedule; platform retention still applies to
completed recovery points.
Namespace deletion removes these resources. Storage retained outside the
namespace needs a separate platform backup policy.

### PostgreSQL retention with Kyverno

CloudNativePG does not prune volume snapshots. Configure platform retention
before use. The example below uses Kyverno's
[NamespacedDeletingPolicy](https://kyverno.io/docs/policy-types/deleting-policy/)
to remove completed cold Backups older than seven days. Kubernetes then removes
their owned snapshots. It checks once an hour and does not target other stores.

Use a Kyverno installation that serves `policies.kyverno.io/v1`
`NamespacedDeletingPolicy`. Replace `team-demo`, `postgres-main`, and
`postgres-snapshot-main` with the Datalab namespace, native cluster name, and
schedule name. Replace the RoleBinding subject with the installed cleanup
controller's ServiceAccount and namespace. This grants additional Backup access
only in the selected namespace. Provider Datalab does not install Kyverno or
this policy.

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: postgres-backup-retention
  namespace: team-demo
rules:
- apiGroups: [postgresql.cnpg.io]
  resources: [backups]
  verbs: [get, list, watch, delete]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: postgres-backup-retention
  namespace: team-demo
subjects:
- kind: ServiceAccount
  name: kyverno-cleanup-controller
  namespace: kyverno
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: postgres-backup-retention
---
apiVersion: policies.kyverno.io/v1
kind: NamespacedDeletingPolicy
metadata:
  name: postgres-backup-retention
  namespace: team-demo
spec:
  schedule: '15 * * * *'
  deletionPropagationPolicy: Background
  matchConstraints:
    resourceRules:
    - apiGroups: [postgresql.cnpg.io]
      apiVersions: [v1]
      resources: [backups]
    objectSelector:
      matchLabels:
        cnpg.io/scheduled-backup: postgres-snapshot-main
  conditions:
  - name: selected-namespace
    expression: object.metadata.namespace == 'team-demo'
  - name: completed-cold-backup
    expression: >-
      object.spec.cluster.name == 'postgres-main' &&
      object.spec.method == 'volumeSnapshot' &&
      has(object.spec.online) && object.spec.online == false &&
      has(object.status) && has(object.status.phase) &&
      object.status.phase == 'completed'
  - name: older-than-one-week
    expression: >-
      time.now() - timestamp(object.metadata.creationTimestamp) > duration('168h')
```

This policy uses age, not a count or the time of the last successful backup.
Long backup failures can leave no recovery point after seven days. Monitor
failed backups and disable cleanup during recovery. Test the policy with the
platform's Kyverno version before enabling deletion.

## Network policies

Provider Datalab creates ingress and egress policies in the Datalab-named host
service namespace. This namespace is the team boundary. Services, virtual
control planes, and synced workload Pods use it regardless of their virtual
namespace. Virtual clusters in one Datalab share this boundary.
The cluster CNI must enforce Kubernetes NetworkPolicy for these rules to take
effect.

PostgreSQL also has a service policy. It permits the CloudNativePG controller
Pods in `database.operatorNamespace` to reach TCP ports 5432 and 8000. Database
Pods can reach Kubernetes API ports 443 and 6443 and cluster DNS. The controller
Pods must have label `app.kubernetes.io/name: cloudnative-pg`.
The API-port rules have no destination IP selector because API endpoints can
use host networking. Platform controls can restrict their destination addresses.

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

Each named volume with backups enabled adds a policy for its host backup Job Pods. It permits DNS
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

Valkey snapshot Jobs use the same class role and namespaced snapshot permissions,
plus permission to patch the verified label after consistency checks.
Each Job can read its selected Pod and data PVC. Its mounted backup credential
permits `PING`, `INFO`, `BGSAVE`, `CLIENT PAUSE`, and `CLIENT UNPAUSE`, with no key
read or write commands. The Job pauses writes for at most 11 minutes, saves an
RDB file, and captures the PVC. A server replacement or an expired pause rejects
the capture. The Job releases writes on exit; the timeout also releases them
after a killed Job. Valkey network access includes TCP 6379 in the service namespace.

## Health checks

Kubernetes uses startup probes to allow initialization, readiness probes to
remove unavailable Pods from Service endpoints, and liveness probes to restart
an unresponsive process.

| Component | Readiness | Liveness and startup |
| --- | --- | --- |
| Data (`package-r`) | HTTP `/health` | HTTP `/health` |
| Data OAuth proxy | HTTP `/ready` | HTTP `/ping` |
| S3 gateway | Gateway forwards `/_ready` to its OAuth proxy | Local `/_live` response |
| S3 OAuth proxy | Gateway forwards `/_auth/ready` to loopback port 4180 | Gateway forwards `/_auth/ping` |
| S3 rclone | Authenticated S3 listing through its local listener | Local unsigned HTTP request must return `403 Forbidden` |
| Registry | `/debug/health` on private port 5001, including the storage driver | TCP port 5000 for liveness; `/debug/health` for startup |
| Valkey | Authenticated local `PING` | Authenticated local `PING`; startup allows ten minutes for data replay |
| Virtual cluster | HTTPS `/readyz` | HTTPS `/healthz` for liveness; `/readyz` for startup |
| PostgreSQL | CloudNativePG instance manager `/readyz` | CloudNativePG instance manager `/healthz` and `/startupz` |
| Crossplane core | HTTP `/readyz` on port 8081 | HTTP `/healthz` on port 8081 |
| Crossplane RBAC manager | HTTP `/metrics` on port 8080 | Same local HTTP listener; this manager has no health endpoint |
| Kubernetes provider | HTTP `/readyz` on port 8081 | HTTP `/healthz` on port 8081 |
| Keycloak provider | HTTP `/metrics` on port 8080 | Same local HTTP listener; this provider has no health endpoint |
| Composition functions | TCP on TLS port 9443 | Same listener; native Kubernetes gRPC probes do not support TLS |

Valkey checks that the mounted ACL matches the configured checksum before startup.

Registry liveness checks the local listener, so an object-storage outage makes
the Pod unready without causing repeated restarts. Its health port is absent
from the Service and public routes. The rclone liveness request uses its
loopback listener and stops at local authentication, before object-storage access.

CloudNativePG and vCluster supply probes for their managed components. The
Crossplane Helm post-renderer adds probes to the core and RBAC manager; it needs
Python with PyYAML. The provider runtime configs set probes for providers and functions. Backup,
cleanup, and initialization tasks exit when complete; Jobs use deadlines and
completion status instead of liveness probes.
