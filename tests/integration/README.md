# Integration tests

The suite can use an existing test cluster or the `provider-datalab-it` Kind
cluster. Every Kubernetes and Helm call uses an explicit kubeconfig and context.
Kind is the default; its context is `kind-provider-datalab-it` and its kubeconfig
is `/tmp/provider-datalab-it.kubeconfig`.

Setup installs Crossplane with [the supplied Helm values](../../deploy/crossplane-values.yaml)
and dependencies from `dependencies/`. Versions are listed in the
[installation guide](../../docs/how-to-guides/installation.md#dependency-baseline).
It applies the current XRD and Composition and waits for the generated Datalab
CRD schema to match. A disposable MinIO supplies storage; Provider Storage is
not installed or tested.

## Select a cluster

For an existing cluster, supply its kubeconfig, context, StorageClass, Service
CIDR, and comma-separated Pod CIDRs. Use values from the selected cluster:

```bash
tests/integration/run.bash all \
  --kubeconfig /tmp/datalab-test.kubeconfig --context datalab-test \
  --storage-class standard-rwo \
  --service-cidr 10.20.0.0/16 --pod-cidrs 10.30.0.0/16 \
  --image-registry registry.acme.com/team/integration
```

Add `--check` to check access and settings without installing resources. An
existing cluster needs permission for CRDs, admission policies, and service
account impersonation. The suite installs Crossplane and database operators.
Existing prerequisite namespaces must have the label
`datalabs.versioneer.at/integration=true`; otherwise setup stops before it
changes them. Use namespaces and cluster-wide resources reserved for tests.

NetworkPolicy traffic checks run only in Kind. Existing clusters still run
resource-default and quota checks. Virtual network policies do not prove
isolation when all workloads share one physical host namespace.

The registry must accept pushes and be reachable from cluster nodes. The
runner uses an empty Docker config unless you supply `--docker-config <directory>`
with a config prepared for the test. To use published images,
omit `--image-registry` and set `S3_CLIENT_IMAGE`, `VCLUSTER_CLIENT_IMAGE`, and
`VCLUSTER_CATALOG_IMAGE`. Build them from the matching Dockerfiles in this
checkout. For private images, create a pull Secret in `workspace` and pass its
name with `--image-pull-secret`. The suite copies it to the S3 client namespace
and binds it into the nested catalog namespace.

Standalone profile scripts use `PROVIDER_DATALAB_CLUSTER=existing`,
`PROVIDER_DATALAB_KUBECONFIG`, and `PROVIDER_DATALAB_CONTEXT` for the target.
Set `PROVIDER_DATALAB_STORAGE_CLASS`, `PROVIDER_DATALAB_SERVICE_CIDR`, and
`PROVIDER_DATALAB_POD_CIDRS` to the same values used by the runner. Set
`PROVIDER_DATALAB_IMAGE_REGISTRY` when the profile builds remote images.

## Run profiles

Run the [unit suite](../README.md#run-the-suite) first. Then run all profiles
with one platform setup, or select a profile from the table below:

```bash
tests/integration/run.bash all
tests/integration/run.bash verify-s3
```

Without an existing target, the runner creates or reuses the dedicated Kind
cluster. `--kind` selects this mode explicitly. It reuses matching
dependency releases after readiness checks. To apply charts again after changing
values, set `REUSE_DEPENDENCIES=0`:

```bash
REUSE_DEPENDENCIES=0 tests/integration/run.bash verify-s3
```

Successful profiles remove their test resources. Failed profiles keep them for
diagnosis. To keep successful resources, set the matching variable to `1`:

| Profile | Variable |
| --- | --- |
| Network | `KEEP_NETWORK_RESOURCES` |
| Data | `KEEP_DATA_RESOURCES` |
| S3 | `KEEP_S3_RESOURCES` |
| Registry | `KEEP_REGISTRY_RESOURCES` |
| PostgreSQL | `KEEP_POSTGRES_RESOURCES` |
| MongoDB or Redis | `KEEP_STORE_RESOURCES` |
| Virtual clusters | `KEEP_VCLUSTER_RESOURCES` |

## Datalab manifests by profile

| Profile | Fixture | Checks |
| --- | --- | --- |
| `verify-network` | [Two Datalabs](manifests/network/datalabs.yaml) | Resource defaults and quota rejection. Kind also checks namespace isolation, external egress, and MinIO access. |
| `verify-registry` | [Registry](manifests/registry/datalab.yaml) | Authenticate with the published Secret, then write and read a blob in S3-backed storage. |
| `verify-data` | [Data](manifests/data/datalabs.yaml) | File write/read, credential rotation with restart, and read-only write rejection. |
| `verify-s3` | [S3](manifests/s3/datalab.yaml) | TLS, list/HEAD/GET/range reads, write/delete rejection, and browser access after S3 is disabled. |
| `verify-postgres` | [PostgreSQL](manifests/postgres/datalab.yaml) | SQL write/read through connection Secrets; backup configuration enabled on `pg0` and absent on `pg1`. |
| `verify-mongo` | [MongoDB](manifests/mongo/datalab.yaml) | Document write/read; back up and restore the probe document with oplog replay in a separate MongoDB process. |
| `verify-redis` | [Redis](manifests/redis/datalab.yaml) | Key write/read; restore a backup in a separate Redis process, then disable backups and retain the backup PVC. |
| `verify-vcluster` | [Virtual clusters](manifests/vcluster/datalab.yaml) | Access, routing, workload and STAC behavior, and storage persistence. See below. |

The fixtures use profile-named prerequisite Secrets and disable services outside
their checks. Most use `datalab` or `datalab-custom`; the virtual cluster profile
uses `datalab-vcluster-it`. Network and Data restore the common environment
settings. Network sets different external-egress policies on the two environments;
S3 replaces `datalab-custom` with its Gateway and identity settings.

## Network and service checks

Network probes use controlled HTTP targets and wait for policy convergence.
A blocked connection must fail with a connection error or timeout; HTTP, DNS,
and command errors fail the test. The external target is `https://www.iana.org/`.
A peer outside the team namespaces checks denied ingress. Server-side dry runs
check host LimitRange defaults and all four CPU and memory quota fields.

Data probes use the runtime Service. The test allows ten minutes for deployment
creation because watch throttling can delay generated resources.

S3 installs Contour and Keycloak. Its boto3 client uses `s3-credentials.py` as
`credential_process`. The test pauses the Keycloak client, changes its source
Secret, and checks credential propagation, sanitized observer status, and
workload restart. It restores the Secret, resumes the client, waits for 30 seconds
without Secret updates, and repeats the S3 checks. The Keycloak credential itself
is unchanged.

Database probes run in `workspace`, where connection Secrets are published.
The test policies allow labeled service probes on PostgreSQL, MongoDB, and Redis
ports and block other outside clients. Operators and CRDs use the versions in
the [installation guide](../../docs/how-to-guides/installation.md#prerequisites).

## Virtual cluster checks

The profile installs PGO, Keycloak, and Contour and uses a disposable certificate
for `*.lab.acme.com`. Its CPU limit quota is `20` so two control planes, their
controllers, DNS, PostgreSQL, and the catalog can perform rolling updates.

The `test-login` client uses generated passwords to obtain user tokens.
Checks cover members, administrators, unauthorized profiles, exact roles and
audiences, and rejection of interactive scopes during token exchange.

The workspace service account starts with `ws_api` only. The test assigns
individual vcluster roles and requests their optional scopes. It checks
namespace access, denied escalation, role downgrade, and revocation of tokens
that have not expired. Downloaded helpers must return the caller token unchanged.

Storage checks mount a provider-managed named PVC in ordinary Pods. Workload
replacement, vCluster hibernation, and control-plane restart must keep the
same claim and files. Oversized virtual Pods must report host CPU and memory
quota rejection. Controller installation uses only the virtual API.
CSI backup and restore require a snapshot-capable test target.

Other checks cover OAuth2 discovery names, source Secret deletion and recovery,
and different custom Secrets for John and Jane. STAC item search must still work
after both instances hibernate and resume and after a control-plane restart.
Hibernation must remove their synced Pods, keep the same PVCs, and leave PostgreSQL
ready. Removing one virtual cluster must leave the
other cluster and PostgreSQL available.

## Test resource budget

A full run shares one selected cluster. Unused database operators are scaled to zero.
Each store profile starts its operator and waits for readiness. Cleanup waits for
resource deletion before stopping the operator; failures leave it running.
Crossplane, providers, storage, and identity services stay available.

The runner reports setup and profile durations and CPU requests. Run
`tests/integration/resource-budget.bash` to inspect active Pod and init-container
requests, unscheduled requests, and node allocation. The report shows CPU
reserved for scheduling. Probe and backup Pods have 90 seconds to
schedule; execution timeouts start after scheduling. Failures report events and
the resource budget.

Integration builds a separate Composition artifact with a `1m` Python TTL default.
Environment overrides and the separate environment and auto-ready TTLs still
apply. See [build settings](../../templates/README.md).

## GitHub Actions

The [workflow](../../.github/workflows/pr.yaml) uses the
[shared check selection](../README.md#select-checks). Runtime changes and manual
runs execute the full unit suite and all eight profiles in one Kind cluster.
Documentation-only changes run documentation and static checks. The final
required check waits for every selected job.

Tag publication requires a successful push test run for the tagged commit and
does not repeat tests. Use tags such as `1.0.0`, without a `v` prefix.
