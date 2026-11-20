# Dedicated Kind integration environment

The integration tests use only the `provider-datalab-it` Kind cluster and the
`kind-provider-datalab-it` context. The default kubeconfig is
`/tmp/provider-datalab-it.kubeconfig`. The scripts do not use another local
cluster or the default kubeconfig.

The harness tests Provider Datalab behavior. It does not install or test
Provider Storage. It creates fixed profile-named Secrets for the disposable
in-cluster MinIO service because the Datalab composition needs object-storage
credentials.

Platform setup waits for the generated Datalab CRD schema to match the XRD.

The harness installs Crossplane core `2.4.3` and applies
[`deploy/crossplane-values.yaml`](../../deploy/crossplane-values.yaml) on every
setup. Provider and function settings come from `dependencies/`. See the
[dependency baseline](../../docs/how-to-guides/installation.md#dependency-baseline).

Run the render tests before cluster integration:

```bash
tests/unit.bash
```

## Datalab manifests by profile

| Profile | Datalabs | What the test verifies |
| --- | --- | --- |
| `verify-network` | `verify-network-open` and `verify-network-closed` from [manifests/network/datalabs.yaml](manifests/network/datalabs.yaml) | Same-namespace access, cross-namespace ingress and egress isolation, explicit MinIO access, external egress settings, host LimitRange defaults, and CPU/memory quota rejection. |
| `verify-registry` | `verify-registry` from [manifests/registry/datalab.yaml](manifests/registry/datalab.yaml) | The registry runs in the Datalab service namespace and uses S3 storage. The test uses the published connection Secret to authenticate and write and read a blob. |
| `verify-data` | `verify-data-enabled` from [manifests/data/datalabs.yaml](manifests/data/datalabs.yaml) | File write/read, one credential update with workload restart, and read-only write rejection through the generated Secret. Render tests cover disabled Data and resource structure. |
| `verify-s3` | `verify-s3` from [manifests/s3/datalab.yaml](manifests/s3/datalab.yaml) | Experimental S3 access with the generated Datalab client: TLS routing, list/HEAD/GET/range reads, write/delete rejection, shared browser hostname, and browser access after S3 is disabled. |
| `verify-postgres` | `verify-postgres` from [manifests/postgres/datalab.yaml](manifests/postgres/datalab.yaml) | SQL write and read through the generated connection Secret for `pg0` with backups and `pg1` with zero backup storage. Checks that `pg1` has no backup configuration and its composed Object becomes ready. |
| `verify-mongo` | `verify-mongo` from [manifests/mongo/datalab.yaml](manifests/mongo/datalab.yaml) | Document write and read through the generated connection Secret. Runs the backup CronJob and restores its archive with oplog replay into an isolated local MongoDB process. Checks the restored probe document. |
| `verify-redis` | `verify-redis` from [manifests/redis/datalab.yaml](manifests/redis/datalab.yaml) | Key write and read through the generated connection Secret. Enables backups on the running store, runs the CronJob, and checks the restored value in an isolated Redis process. Disables backups and checks that the backup PVC remains and Redis still accepts writes. |
| `verify-vcluster` | `verify-vcluster` | Two virtual clusters, per-instance HTTPS routing, profile and member authorization, streaming, role revocation, independent removal, and a PostgreSQL-backed STAC catalog. Checks Sandbox CRDs and controllers, sandboxd command and file APIs, and session PVC data after workload replacement. |

All Datalabs use a matching profile-named prerequisite Secret. The Data
fixture and the S3 fixture enable Data. Each profile removes its successful
test resources. A failed profile keeps its resources for diagnosis.

## Run profiles locally

Each command creates or reuses the dedicated cluster, applies the current
source manifests, and runs one profile. Matching dependency releases are reused:

```bash
tests/integration/run.bash all              # Full suite; one shared platform setup.
tests/integration/run.bash verify-network
tests/integration/run.bash verify-data
tests/integration/run.bash verify-s3
tests/integration/run.bash verify-postgres
tests/integration/run.bash verify-mongo
tests/integration/run.bash verify-redis
tests/integration/run.bash verify-registry
tests/integration/run.bash verify-vcluster
```

The network profile uses controlled HTTP targets to test generated policies.
Connection checks run after the policies have converged. A denied connection
must fail with a connection error or timeout; an HTTP, DNS, or command error fails
the check. The external connectivity target is `https://www.iana.org/`.
An unrestricted peer also checks denied ingress into both team namespaces.
Server-side dry runs check that the host LimitRange supplies missing container
resources and that all four CPU and memory quotas reject oversized Pods.
Set `KEEP_NETWORK_RESOURCES=1` to retain successful resources.

The Data profile checks file access through the runtime Service. It allows
ten minutes for deployment creation because watch throttling can delay
resource generation. Set `KEEP_DATA_RESOURCES=1` to retain successful resources.
The registry profile uses `KEEP_REGISTRY_RESOURCES=1`.

The network, Data, and store fixtures use `datalab` and `datalab-custom`.
The virtual cluster profile uses `datalab-vcluster-it` for its issuer,
Gateway, and Secret binding settings. Profiles disable services outside their checks.
The network and Data profiles restore the common environment
settings before creating their Datalabs. The network profile disables
external egress in `datalab` and enables external egress
in `datalab-custom`. The S3 profile replaces
`datalab-custom` with its Gateway and identity settings.

The S3 profile installs Contour and Keycloak. Its boto3 client uses
`s3-credentials.py` as `credential_process`. It pauses the test Keycloak
client, changes its source Secret, and checks redacted observer status,
credential propagation, and workload restart. After restoring the Secret and
resuming the client, it requires 30 seconds without Secret updates and repeats
the S3 checks. This changes the Kubernetes Secret, not the Keycloak credential.
Set `KEEP_S3_RESOURCES=1` to retain successful resources.

The store profiles use the operator versions listed in the
[installation guide](../../docs/how-to-guides/installation.md#prerequisites).
Set `KEEP_POSTGRES_RESOURCES=1` for PostgreSQL, or `KEEP_STORE_RESOURCES=1` for
MongoDB and Redis, to retain successful resources. The harness applies CRDs
before installing an operator. Operators remain installed and are scaled down
after successful cleanup.

Service probes run in `workspace`, where the published connection Secrets live.
The test environment permits ingress only from Pods with the service-probe label
on PostgreSQL, MongoDB, and Redis ports. Other outside clients remain blocked.

Dependencies with matching pins are reused after readiness checks. Set
`REUSE_DEPENDENCIES=0` to apply the chart again, for example after
changing chart values. The current Composition and XRD are applied on each run.
The S3 client image is rebuilt when its source changes and loaded only when
absent from Kind. Full runs start Keycloak before the network and
Data profiles so that its startup can run at the same time. The S3 profile
waits for it before making requests. The runner prints setup and profile durations.

```bash
REUSE_DEPENDENCIES=0 tests/integration/run.bash verify-s3
```

## GitHub Actions

The [test workflow](../../.github/workflows/pr.yaml) uses the
[shared classifier](../README.md#select-checks). Documentation-only changes run
the documentation and static checks. Other changes and manual runs execute
the unit suite and all eight integration profiles. The profiles share one
Kind cluster in the job. The final required check waits for every selected
job. Tag publication requires a successful push test run for the tagged commit
and does not repeat the tests. Use release tags such as `1.0.0`, without a
`v` prefix.

## Virtual cluster checks

Platform setup creates a fresh disposable TLS certificate for `*.lab.acme.com`.
The profile sets `defaults.overallQuota.hard.limits.cpu` to `20`. Its two
control planes, controllers, DNS, database, and catalog need room for rolling
updates. Other quota entries keep their defaults.

The profile installs PGO, Keycloak, and Contour. Its `test-login` client uses
a password grant to obtain human subject tokens with generated test passwords.
Exchange checks cover members, administrators, unauthorized profiles, exact
roles and audiences, and rejection of interactive scopes.

The workspace service account starts with only `ws_api`. The test temporarily
assigns individual vcluster roles and requests their optional scopes. It checks
namespace access, denied escalation, independent instances, role downgrade,
and revocation with tokens that have not expired. Downloaded profile helpers
must return the caller token unchanged.

Sandbox checks use REST, gRPC, and Kubernetes port-forwarding. They replace a
Sandbox and verify the file content and session PVC UID. Oversized virtual
Pods must report host CPU and memory quota rejection.

The profile also checks OAuth2 discovery name uniqueness and recovery after
source Secret deletion. Custom connection checks use different optional
Secrets for John and Jane. The PostgreSQL-backed STAC test creates and searches
an item, then repeats the search after API and control-plane restarts. Removing
one virtual cluster must leave the other cluster and PostgreSQL available.

## Test resource budget

All profiles in a full run use one Kind cluster. CI creates a fresh cluster;
local runs reuse the dedicated cluster. The platform setup scales unused
PostgreSQL, MongoDB, and Redis operators to zero. Each database profile scales
its operator to one and waits for readiness, including when it reuses a Helm
release. Successful cleanup waits for resource deletion before scaling it down.
An operator stays running if resources remain or cleanup fails. Crossplane,
providers, storage, and identity services remain available.

Integration builds a temporary composition with a `1m` Python response TTL
default. Environment settings can override it. The environment and auto-ready
functions keep their separate `10m` TTLs. The deployment artifact stays unchanged.

The runner and CI report CPU requests at profile boundaries. Backup and probe
checks also report requests before they run. The report includes active Pod
requests, init-container requirements, unscheduled requests, and node allocation.
Use `tests/integration/resource-budget.bash` to read the current budget.
This reports scheduler reservations, not measured CPU use.

A probe or backup Pod has 90 seconds to schedule before its execution wait.
An unscheduled Pod reports its events, CPU request budget, and node allocation.
The longer backup completion wait starts only after scheduling succeeds.
