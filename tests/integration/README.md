# Dedicated Kind integration environment

The integration tests use only the `provider-datalab-it` Kind cluster and the
`kind-provider-datalab-it` context. The default kubeconfig is
`/tmp/provider-datalab-it.kubeconfig`. The scripts do not use another local
cluster or the default kubeconfig.

The harness tests Provider Datalab behavior. It does not install or test
Provider Storage. It creates fixed profile-named Secrets for the disposable
in-cluster MinIO service because the Datalab composition needs object-storage
credentials.

Crossplane `2.4.1` is the reproducible test pin. See
[`crossplane.yaml`](../../crossplane.yaml) for the supported Crossplane range.

Run the render tests before cluster integration:

```bash
tests/unit.bash
```

## Datalab manifests by profile

| Profile | Datalabs | What the test verifies |
| --- | --- | --- |
| `verify-network` | `verify-network-open` and `verify-network-closed` from [manifests/network/datalabs.yaml](manifests/network/datalabs.yaml) | The closed Datalab disables external egress and vCluster access. The open Datalab enables both. The test applies their generated NetworkPolicies and verifies namespace isolation, MinIO, a controlled target with vCluster labels, and external access. |
| `verify-registry` | `verify-registry` from [manifests/registry/datalab.yaml](manifests/registry/datalab.yaml) | The Datalab starts one session and retains one stopped session. Its shared registry uses S3 storage. The test uses the published connection Secret to authenticate and write and read a blob. |
| `verify-data` | `verify-data-enabled` from [manifests/data/datalabs.yaml](manifests/data/datalabs.yaml) | File write/read, one credential update with workload restart, and read-only write rejection through the generated Secret. Render tests cover disabled Data and resource structure. |
| `verify-s3` | `verify-s3` from [manifests/s3/datalab.yaml](manifests/s3/datalab.yaml) | Experimental S3 access with the generated Datalab client: TLS routing, list/HEAD/GET/range reads, write/delete rejection, shared browser hostname, and browser access after S3 is disabled. |
| `verify-postgres` | `verify-postgres` from [manifests/postgres/datalab.yaml](manifests/postgres/datalab.yaml) | SQL write and read through the generated connection Secret for `pg0` with backups and `pg1` with zero backup storage. Checks that `pg1` has no backup configuration and its composed Object becomes ready. |
| `verify-mongo` | `verify-mongo` from [manifests/mongo/datalab.yaml](manifests/mongo/datalab.yaml) | Document write and read through the generated connection Secret. Runs the backup CronJob and restores its archive with oplog replay into an isolated local MongoDB process. Checks the restored probe document. |
| `verify-redis` | `verify-redis` from [manifests/redis/datalab.yaml](manifests/redis/datalab.yaml) | Key write and read through the generated connection Secret. Enables backups on the running store, runs the CronJob, and checks the restored value in an isolated Redis process. Disables backups and checks that the backup PVC remains and Redis still accepts writes. |
| `verify-vcluster` | `verify-vcluster` | Two virtual clusters, per-instance HTTPS routing, implicit admin profiles, member token claims and membership removal, caller role isolation, credential-free profiles, streaming, PVC persistence, role downgrade and revocation, independent removal, and a PostgreSQL-backed STAC catalog. |

All Datalabs use a matching profile-named prerequisite Secret. The Data
fixture and the S3 fixture enable Data, and only the registry fixture starts a
session. Each profile removes its successful test resources. A failed profile
keeps its resources for diagnosis.

## Run profiles locally

Each command creates or reuses the dedicated cluster, applies the current
source manifests, and runs one profile. Matching dependency releases are reused:

```bash
tests/integration/run.bash all              # Full suite; one shared platform setup.
tests/integration/run.bash verify-network
tests/integration/run.bash verify-registry
tests/integration/run.bash verify-data
tests/integration/run.bash verify-s3
tests/integration/run.bash verify-postgres
tests/integration/run.bash verify-mongo
tests/integration/run.bash verify-redis
tests/integration/run.bash verify-vcluster
```

The network profile uses controlled HTTP targets to test generated policies.
It does not start a real vCluster or test admission policy. Each connection
check runs once after the policies have converged. A denied connection must
fail with a connection error or timeout; an HTTP, DNS, or command error fails
the check. The external connectivity target is `https://www.iana.org/`.
Set `KEEP_NETWORK_RESOURCES=1` to retain successful resources.

The registry profile installs Kyverno because the session runtime applies
Kyverno policies. It then installs the EOEPCA+ dependency chart `2.2.1`, which
contains the Educates session runtime `3.7.1`. Set `KEEP_REGISTRY_RESOURCES=1` to
retain successful resources.
The profile creates the required disposable MinIO bucket before the Datalab.
The registry probe allows time for the HTTP service to start. It reports
the failed operation and HTTP status without printing credentials.

The Data profile reuses the session runtime installation and seeds one
disposable MinIO bucket for file operations. It tests access through the
runtime Service.
It allows ten minutes for deployment creation. Startup watch throttling can
delay resource generation after the runtime Secret observer is ready.
Set `KEEP_DATA_RESOURCES=1` to retain successful resources.

Integration fixtures also use only `datalab` and `datalab-custom`; profiles
explicitly disable services that are outside their checks.
The network, registry, and Data profiles restore the common environment
settings before creating their Datalabs. The network profile disables
external egress in `datalab` and enables external egress and vCluster access
in `datalab-custom`. The S3 profile replaces
`datalab-custom` with its Gateway and identity settings.

The S3 profile adds Contour, Keycloak, and an SDK client to test
[S3 client access](../../docs/how-to-guides/s3-access.md).
The boto3 client uses `s3-credentials.py` as its AWS `credential_process`.
The test Pod receives `CLIENT_SECRET` from the generated Datalab OAuth Secret.
The S3 profile also pauses its disposable Keycloak client, changes the source
OAuth connection Secret, and checks credential propagation and workload
restart. It restores the credentials, resumes the client, and requires 30
seconds without updates to the source, observer, and projected Secrets.
It then repeats the S3 checks. This tests Secret propagation; it does not
rotate credentials in Keycloak itself.
Set `KEEP_S3_RESOURCES=1` to retain successful resources.

The PostgreSQL profile installs Crunchy PGO `6.0.2`.
Set `KEEP_POSTGRES_RESOURCES=1` to retain successful
resources. PGO remains installed after the profile finishes. Successful cleanup scales
its Deployment to zero. The next profile scales it to one before use.

The managed-store profiles use these fixed operator releases to check the
resources emitted by the composition:

- MongoDB Kubernetes Operator `1.14.0` (Helm chart `1.14.0`) serves
  `mongodbcommunity.mongodb.com/v1`.
- Opstree Redis Operator `0.27.0` (Helm chart `0.27.0`) serves
  `redis.redis.opstreelabs.in/v1beta2`.

Set `KEEP_STORE_RESOURCES=1` to retain successful MongoDB or Redis
resources. Each operator remains installed after its profile finishes. Successful
cleanup scales it to zero after the Datalab, namespace, workloads, and finalizers
are removed. Retained resources or a cleanup failure keep the operator running.
Before an operator install or upgrade, the harness applies the CRDs from
the selected chart. Helm does not update existing CRDs during an upgrade.

Dependencies with matching pins are reused after readiness checks. Set
`REUSE_DEPENDENCIES=0` to force Helm installation or upgrade, for example after
changing chart values. The current Composition and XRD are applied on each run.
The S3 client image is rebuilt when its source changes and loaded only when
absent from Kind. Full runs start Keycloak before the network, registry, and
Data profiles so that its startup can run at the same time. The S3 profile
waits for it before making requests. The runner prints setup and profile durations.

```bash
REUSE_DEPENDENCIES=0 tests/integration/run.bash verify-s3
```

## GitHub Actions

Pull requests to `main`, pushes to `main`, and manual workflow runs execute the
unit suite and all eight integration profiles. The profiles share one Kind
cluster in the job. Tag publication does not run the tests again. A release tag
must point to a commit that passed the main-branch workflow.

## Cleanup

Delete only the dedicated cluster when the validation cycle is complete:

```bash
KUBECONFIG=/tmp/provider-datalab-it.kubeconfig \
  kind delete cluster --name provider-datalab-it
```

Platform setup creates a fresh disposable TLS certificate for `*.lab.acme.com`.

The session runtime controllers receive read-only CRD discovery permissions
from `manifests/educates-rbac.yaml` before startup. The harness checks both
controller rollouts before it creates a Datalab runtime. Controllers request
CPU and memory so they receive a CPU share under local load. Their health
probes allow five minutes for cold starts.

The vcluster profile installs the session runtime, PGO, Keycloak, and Contour.
Its identity fixture creates `test-login` to check exchange of tokens from
another client. The test EnvironmentConfig explicitly adds it through
`iam.extraAudiences`. The fixture permits a password grant to obtain real human
subject tokens. User passwords are generated at test time. Exchange probes
check member and admin subjects, exact roles and
audiences, omission of an unauthorized profile, rejection of interactive scopes,
and namespace access with signed exchanged tokens. The test also checks that
the separate login client's tokens contain the expected group roles and workspace audience.
These probes run only in the dedicated Kind cluster. Passing render checks
does not establish a live result.

It requires one workspace OAuth2 client and verifies that every downloaded
profile rejects the service account with only `ws_api`. The test explicitly
assigns one vcluster role at a time, obtains a token, then removes that grant.
Test requests explicitly include the required optional OAuth scope. The profile
checks that an admin profile cannot elevate a namespace caller and that role
scopes and Kubernetes RBAC permit only the configured access. The probe
mounts the workspace credential Secret separately from public profile Secrets.
These test grants are not composition behavior.
The profile also rejects duplicate OAuth2 discovery names and checks removal
and recovery of discovery when the source credential Secret is deleted and
restored. Its producer is paused for that check; credential values stay private.
It checks that John discovers both custom keys and Jane only `apikey-1`,
with missing optional keys omitted from status and readiness checks.
The virtual cluster starts with a native PostgreSQL Secret mapping.
It builds the catalog image, loads it into Kind, and deploys the STAC workload
through the public virtual Kubernetes API. The migration Job installs PgSTAC in a
Datalab PostgreSQL database. The API uses a separate database login. The test
adds a collection and item, runs a spatial search, restarts the API, and checks
the catalog again after a control-plane restart. It then removes one virtual
cluster and checks that the other cluster and PostgreSQL remain available.

## Test resource budget

All profiles in a full run use one Kind cluster. CI creates a fresh cluster;
local runs reuse the dedicated cluster. The platform setup scales unused
PostgreSQL, MongoDB, and Redis operators to zero. Each database profile scales
its operator to one and waits for readiness, including when it reuses a Helm
release. Successful cleanup waits for resource deletion before scaling it down.
An operator stays running if resources remain or cleanup fails. Crossplane,
providers, storage, Educates, and identity services remain available.

Integration uses a temporary composition with a `1m` response TTL. The generated
deployment artifact and its `5m` default remain unchanged. This reduces periodic
reconciliation waits; it does not change image pull or workload startup time.

The runner and CI report CPU requests at profile boundaries. Backup and probe
checks also report requests before they run. The report includes active Pod
requests, init-container requirements, unscheduled requests, and node allocation.
Use `tests/integration/resource-budget.bash` to read the current budget.
This reports scheduler reservations, not measured CPU use.

A probe or backup Pod has 90 seconds to schedule before its execution wait.
An unscheduled Pod reports its events, CPU request budget, and node allocation.
The longer backup completion wait starts only after scheduling succeeds. The
full suite retains MongoDB and Redis backup and restore checks.
