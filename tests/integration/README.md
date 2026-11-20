# Integration tests

The suite uses the `provider-datalab-it` Kind cluster, the
`kind-provider-datalab-it` context, and `/tmp/provider-datalab-it.kubeconfig`.
Scripts reject other clusters and do not use the default kubeconfig.

Setup installs Crossplane with [the supplied Helm values](../../deploy/crossplane-values.yaml)
and dependencies from `dependencies/`. Versions are listed in the
[installation guide](../../docs/how-to-guides/installation.md#dependency-baseline).
It applies the current XRD and Composition and waits for the generated Datalab
CRD schema to match. A disposable MinIO supplies storage; Provider Storage is
not installed or tested.

## Run profiles locally

Run the [unit suite](../README.md#run-the-suite) first. Then run all profiles
with one platform setup, or select a profile from the table below:

```bash
tests/integration/run.bash all
tests/integration/run.bash verify-s3
```

The runner creates or reuses the dedicated cluster. It reuses matching
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
| `verify-network` | [Two Datalabs](manifests/network/datalabs.yaml) | Namespace isolation, external egress, MinIO access, resource defaults, and quota rejection. |
| `verify-registry` | [Registry](manifests/registry/datalab.yaml) | Authenticate with the published Secret, then write and read a blob in S3-backed storage. |
| `verify-data` | [Data](manifests/data/datalabs.yaml) | File write/read, credential rotation with restart, and read-only write rejection. |
| `verify-s3` | [S3](manifests/s3/datalab.yaml) | TLS, list/HEAD/GET/range reads, write/delete rejection, and browser access after S3 is disabled. |
| `verify-postgres` | [PostgreSQL](manifests/postgres/datalab.yaml) | SQL write/read through connection Secrets; backup configuration enabled on `pg0` and absent on `pg1`. |
| `verify-mongo` | [MongoDB](manifests/mongo/datalab.yaml) | Document write/read; back up and restore the probe document with oplog replay in a separate MongoDB process. |
| `verify-redis` | [Redis](manifests/redis/datalab.yaml) | Key write/read; restore a backup in a separate Redis process, then disable backups and retain the backup PVC. |
| `verify-vcluster` | [Virtual clusters](manifests/vcluster/datalab.yaml) | Access, routing, Sandbox and STAC behavior, and storage persistence. See below. |

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

Sandbox checks use REST, gRPC, and port-forwarding. Replacing a Sandbox must
preserve its file content and session PVC UID. Oversized virtual Pods must report
host CPU and memory quota rejection.

Other checks cover OAuth2 discovery names, source Secret deletion and recovery,
and different custom Secrets for John and Jane. STAC item search must still work
after API and control-plane restarts. Removing one virtual cluster must leave the
other cluster and PostgreSQL available.

## Test resource budget

A full run shares one Kind cluster. Unused database operators are scaled to zero.
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
