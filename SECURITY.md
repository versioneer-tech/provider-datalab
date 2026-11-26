# Security policy

## Supported releases

Security fixes apply to the latest stable release. The latest `0.12.x` release
is also supported while that release line is maintained. Release candidates
are for testing; they are not supported production releases.

Daily scans select the latest stable release, the latest supported `0.12.x`
release, and the newest RC for a version newer than the latest stable release.
Without a stable release, they select the newest RC. Selection uses version
numbers and excludes drafts. Superseded RCs are not scanned automatically.

## Report a vulnerability

Send private reports to `oss@versioneer.at`. Do not open a public issue for a
vulnerability. Include the affected release or commit, reproduction steps,
expected and actual behavior, possible impact, and a proposed fix if available.
Do not send live credentials, tokens, private data, or complete cluster logs.

Maintainers assess the report, coordinate a fix, and agree on disclosure with
the reporter where possible. Response times depend on maintainer availability;
this project does not promise a fixed response or repair time.

## Build and release checks

The workflows use the same scripts as local checks. Check jobs have read-only
repository access. Only package/release publication and documentation jobs
receive the writes they need. PR checks receive no publication credentials.

| Check | Scope |
| --- | --- |
| File checks | Strict documentation, generated composition, copyright, workflow validation, and redacted Gitleaks scans of current repository files. Full Git history is not scanned. |
| Runtime checks | Full units and all integration profiles for code changes. Draft PRs defer cluster tests. |
| Source dependencies | Trivy scans pinned Python and Go manifests, including build, documentation, hook, audit, integration-client, and admission-test dependencies. pip-audit checks all six Python locks. govulncheck independently checks the admission-test Go source. |
| Package candidate | Crossplane builds a Configuration package. Its contents must match the three source manifests. Checksums and the OCI manifest digest bind the saved package to its source archive and inventories. |
| External components | Trivy scans default service images, provider/function packages, test Dockerfile bases, and the Kind node by saved digest for Linux AMD64. Each scan produces a CycloneDX JSON SBOM. |

The final `required_checks` job rejects failed, cancelled, missing, and
unexpectedly skipped required jobs. Documentation-only changes require the
documentation/file job and expect runtime/security jobs to be skipped. Other
changes require all jobs. Manual Tests runs always select the full suite.
The repository's effective branch rules must require this status.

### Dependency updates and tool installation

Dependabot checks Action, Python, and Go dependencies weekly and Dockerfiles
and image fields in configured YAML directories daily, including weekends.
Routine minor and patch updates are
grouped by ecosystem; major updates remain separate. Updates to the current
Python base image digests share one group. One Python updater covers all six
dependency sets. Security-update grouping and alerts need separate hosted
verification. Review and test update PRs. Do not apply audit fixes
automatically. Python requirements include exact versions and hashes;
installation requires those hashes. Most installs accept wheels only. The
STAC test image builds `version-parser` 1.0.1 from its fixed source archive,
which has no wheel. Its reviewed `setup.py` imports setuptools, reads README,
and calls `setup`; it contains no download or command execution. The build
uses hash-pinned setuptools and wheel with build isolation disabled. Other
packages use wheels. Test base images and the Kind node use
content digests; Dependabot can propose updates to the Dockerfile pins.

Docker update groups include current-tag digest changes. Docker major updates
are listed by the daily image check for separate manual pull requests; they
are excluded from automatic groups. Other ecosystems keep major updates in
separate Dependabot pull requests.

External Actions use full commit SHAs. The shared tool installer checks fixed
archive SHA-256 values before it installs a binary. Go-built tools use pinned
module versions and module checksums. They also use Go's module checksum
verification for transitive dependencies. The installer does not execute
downloaded shell scripts. There are no external reusable workflows or
composite Actions in these workflow definitions.

Helm charts and downloaded bootstrap manifests use version references. Fixed
content verification for these inputs remains planned.

The [daily image check](.github/workflows/image-updates.yaml) also reads image
defaults in Python, template images, Crossplane provider and function packages,
test Dockerfiles, and the Kind node image. It reports newer version tags and
changed tag digests with at most two concurrent registry queries. It preserves
image variants and lists major updates separately. Registry lookup errors fail
the job. Available updates are reported; the check does not change source or
open pull requests. It does not scan replacement images for vulnerabilities.
Its reports are retained for 90 days.

Dependabot's image parser does not read Python defaults or Crossplane
`spec.package` fields. Maintainers apply updates reported for these inputs.
Custom tool versions and checksums still need manual review. After an update
changes composition sources or templates, regenerate `composition.yaml` and
review affected render fixtures before running the full checks.

The package-r, NGINX gateway, virtual Kubernetes, and updated helper-function
references use versions and digests. Other configurable defaults still use
mutable tags. Release scans record resolved digests; they do not force an
operator's deployment to use those digests.

### Candidate and publication

Contributors and maintainers sign commits. Release tags are unsigned and
created with Git. Before release, review changes since the preceding tag and
prepare the release notes, including behavior changes and security fixes.
Merge the release changes before qualification. Check the effective signed
commit rule; this policy alone does not establish enforcement.

Configure signing on the computer that holds your signing key. For GPG, set
`git config --local user.signingkey <full-key-fingerprint>` and
`git config --local commit.gpgsign true`. Set
`git config --local tag.gpgsign false` to keep release tags unsigned. Register
the public key with your GitHub account; keep the private key on your signing
device. See [GitHub commit signing](https://docs.github.com/en/authentication/managing-commit-signature-verification/signing-commits).
These instructions do not configure keys or prove that a branch rule requires
signed commits. Review and test Dependabot pull requests before merging them.

A release requires a successful full Tests run on the protected default branch
for the exact source commit. PR runs and documentation-only runs do not qualify.
A manual full run can qualify a documentation-only commit.

After the qualifying run succeeds, create an unsigned annotated tag with
`git -c tag.gpgSign=false tag -a <version> <commit> -m <version>`, then push that
tag. The tag starts candidate scanning and publication. If a scan blocks
publication, assess the findings before creating another release. Review the
published assets and documentation after the workflow completes.

The tag workflow builds a versioned candidate, checks its package contents,
then saves it before scans. This artifact contains no executable runtime, so
binary startup and HTTP health smoke tests do not apply. Deployed behavior is
checked by the integration suite, which deploys source manifests. A separate
installation check of the saved `.xpkg` remains planned.

Publication downloads the candidate and scan records by artifact ID. It checks
their hashes, release version, source commit, and package digest before it
pushes the saved archive. It does not rebuild the package. The published
manifest digest must match. An existing tag with a different digest is rejected.

Each GitHub Release includes the package, exact source archive, security
manifest, package SBOM, external component list, dependency SBOMs, and scan
records. `publication.json` records upload IDs and the workflow run; the release
checksum file identifies all attached evidence. Release notes use GitHub's
generated changes. Alpha, beta, and RC tags
are prereleases. Documentation is published after artifacts. Prereleases do
not update stable aliases; an older stable documentation version cannot move
the `latest` alias backward. Publication runs are serialized.

### Scan policy

| Result | Effect |
| --- | --- |
| CRITICAL, with or without a fix | Block publication unless an active exact-image exception applies |
| HIGH with an available fix | Block publication unless an active exact-image exception applies |
| HIGH without an available fix | Report separately; no severity-based automatic block |
| MEDIUM, LOW, UNKNOWN | Retain in reports |
| End-of-support image OS | Block publication |
| Scanner error or missing required inventory, report, or SBOM | Block publication |

Before accepting deferred HIGH risk, maintainers must record an owner, reason,
mitigation where possible, and a review date in the release assessment.
govulncheck findings/errors and pip-audit findings/errors fail their checks
independently of the Trivy severity rules. The workflow uses no vulnerability
filter in the scanner. Secret findings fail the check; reports redact secret values.

### Temporary vulnerability exceptions

The repository owner accepted the current external-image findings, including
CRITICAL findings, on 26 November 2026. This permits work and publication while
maintainers review fixes and image rebuilds. Runtime exposure has not been
assessed. This is a temporary risk acceptance, not a finding that these
components are safe or unaffected.

The [exception policy](scripts/vulnerability-exceptions.json) assigns review to
the Versioneer maintainers at `oss@versioneer.at`. The initial exceptions expire
on **26 December 2026 UTC**. They apply through 25 December. Renewal needs a
new review and a policy change; scans do not extend them automatically.

Each exception matches an immutable image reference, advisory, package name,
installed version, package URL, report target, and severity. A new finding,
changed image digest, or changed finding identity blocks the check unless it
has its own active exception. Expired matching exceptions block again.
Missing or invalid exception policies fail the check.

Scans retain all findings. The gate records accepted findings separately from
remaining blockers and retains the policy, its checksum, owner, reason,
mitigation limits, and expiry with the reports. Release verification checks
the current policy and expiry again; a policy change requires a new scan.
Scheduled release scans use the policy from their workflow checkout, so a
policy change can withdraw an acceptance without changing a published artifact.

These exceptions apply only to external-image vulnerability findings. Source
dependency findings cannot use them. Native audit failures, secret findings,
unsupported operating systems, scanner failures, and missing inventories or
SBOMs remain blocking.
Remove resolved exceptions when images change. Review upstream fixes and
remaining exposure before the expiry date.

The fixed-content exceptions in `scripts/secret-fixtures.json` cover reviewed
synthetic fixtures and template matches. An exception applies only to its
listed detector rules and exact file hash. A changed fixture is scanned and
requires review again; a different detector rule is not suppressed. Full
redacted scanner reports and the exception counts are retained. Do not update
an exception to accept an unexplained match.

Maintainers own assessment of a failed daily scan and a new release when
needed. A default-branch source fix does not change a published package.

### Daily scans and retention

The daily workflow downloads published release assets and verifies their
security manifest. It checks the package at its immutable registry digest and
rescans saved source inputs and external image digests with current
vulnerability data. It does not rebuild or replace releases.
Manual runs accept comma-separated published tags. An empty input selects
supported releases; unknown tags fail. The matrix uses `fail-fast: false` and
`max-parallel: 2`.

Missing release assets or a missing security manifest fail the scan. Existing
tags without GitHub Release evidence need a separate evidence backfill; the
workflow does not create one or substitute current source. With no published
release evidence, selection fails instead of reporting a successful scan.

Candidates are retained for seven days. Reports and SBOMs are retained for
90 days, including failed scans. Release assets retain the inventories and
scan records with the package. `scan-summary.json` records the manifest hash,
scanner/database versions, blocking, accepted, expired, and unfixed HIGH
findings, the exception-policy checksum, errors, and report hashes. Individual
reports retain all severities.

### Coverage and verification limits

The Configuration package has no OS, native runtime, or separately shipped
Python dependencies. Its SBOM records its manifests and package hash.
External image SBOMs describe detected OS, native, Go, and Python packages;
they do not describe a complete deployed platform. Operators can override
images and install other components. Host software, nested runtime and Helm
images, other test-platform and probe images, non-AMD64 images, and deployed
cluster state are outside these scans.
Go build-tool modules and native libraries bundled in build and test wheels do not
have separate vulnerability inventories. These coverage gaps remain planned
work; checksums alone do not establish vulnerability status.

The dedicated Kind CSI driver uses its external tar option for trusted synthetic
snapshots. This preserves file ownership for PostgreSQL recovery; the driver's
Go extractor does not restore ownership. This test setting is not a production
storage configuration and must not process untrusted archives.

Artifact hashes establish content identity. Build attestations and consumer
verification of build origin are deferred until requested. Recovery after partial
publication still needs an operator procedure and hosted validation. A failure
after the registry push can leave a package without a completed GitHub Release
or documentation deployment.

The new workflows require hosted verification after merge. Successful
publication, scheduled execution, Dependabot operation, and effective branch
enforcement are not established by local tests. Branch rules were absent at
the last read-only assessment. They must be configured and verified before
the checks can be described as an enforced release and merge gate.

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

Registry and Valkey passwords are derived from resource names and are
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

Install the [cluster snapshot prerequisites](README.md#cluster-prerequisites)
before enabling PostgreSQL backups. CloudNativePG needs permission to create
and manage its database snapshots. Crossplane's Kubernetes provider observes
the selected snapshot class and checks its `Delete` policy.

Each database backup Job has a separate ServiceAccount. It can read its named
Cluster and snapshot classes, request and remove namespaced CNPG Backups, and
read the resulting VolumeSnapshots. It cannot read Secrets, delete PVCs, or
delete snapshots directly. CloudNativePG sets each snapshot's owner to its
Backup; Kubernetes removes those snapshots when retention removes the Backup.

The Job removes old completed backups only after a new backup and all of its
snapshots are ready. It limits cleanup to its database name and cluster UID.
Disabling backups removes the schedule and leaves completed recovery points.
Namespace deletion removes these resources. Storage retained outside the
namespace needs a separate platform backup policy.

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
