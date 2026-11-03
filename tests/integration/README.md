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
| `verify-registry` | `verify-registry` from [manifests/registry/datalab.yaml](manifests/registry/datalab.yaml) | The Datalab starts one session with a 1 GiB registry. The test authenticates to the session registry and writes and reads a blob. |
| `verify-data` | `verify-data-enabled` from [manifests/data/datalabs.yaml](manifests/data/datalabs.yaml) | File write/read, one credential update with workload restart, and read-only write rejection through the generated Secret. Render tests cover disabled Data and resource structure. |
| `verify-s3` | `verify-s3` from [manifests/s3/datalab.yaml](manifests/s3/datalab.yaml) | Experimental S3 access with the generated Datalab client: TLS routing, list/HEAD/GET/range reads, write/delete rejection, shared browser hostname, and browser access after S3 is disabled. |
| `verify-postgres` | `verify-postgres` from [manifests/postgres/datalab.yaml](manifests/postgres/datalab.yaml) | SQL write and read through the generated connection Secret for `pg0` with backups and `pg1` with zero backup storage. Checks that `pg1` has no backup configuration and its composed Object becomes ready. |
| `verify-mongo` | `verify-mongo` from [manifests/mongo/datalab.yaml](manifests/mongo/datalab.yaml) | Document write and read through the generated connection Secret. Runs the backup CronJob and restores its archive with oplog replay into an isolated local MongoDB process. Checks the restored probe document. |
| `verify-redis` | `verify-redis` from [manifests/redis/datalab.yaml](manifests/redis/datalab.yaml) | Key write and read through the generated connection Secret. Enables backups on the running store, runs the CronJob, and checks the restored value in an isolated Redis process. Disables backups and checks that the backup PVC remains and Redis still accepts writes. |

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
```

The network profile uses controlled HTTP targets to test generated policies.
It does not start a real vCluster or test admission policy. Each connection
check runs once after the policies have converged. A denied connection must
fail with a connection error or timeout; an HTTP, DNS, or command error fails
the check. The external connectivity target is `https://www.iana.org/`.
Set `KEEP_NETWORK_RESOURCES=1` to retain successful resources.

The registry profile installs Kyverno because the Educates runtime applies
Kyverno policies. It then installs the EOEPCA+ Educates dependency chart
`2.2.1`, which contains Educates `3.7.1`. Set `KEEP_REGISTRY_RESOURCES=1` to
retain successful resources.
The registry probe allows time for the HTTP service to start. It reports
the failed operation and HTTP status without printing credentials.

The Data profile reuses the Educates installation and seeds one disposable
MinIO bucket for file operations. It tests access through the runtime Service.
It allows ten minutes for deployment creation. The five-minute composition
response TTL and startup watch throttling can delay resource generation after
the runtime Secret observer is ready.
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
resources. PGO remains installed after the profile finishes.

The managed-store profiles use these fixed operator releases to check the
resources emitted by the composition:

- MongoDB Kubernetes Operator `1.14.0` (Helm chart `1.14.0`) serves
  `mongodbcommunity.mongodb.com/v1`.
- Opstree Redis Operator `0.27.0` (Helm chart `0.27.0`) serves
  `redis.redis.opstreelabs.in/v1beta2`.

Set `KEEP_STORE_RESOURCES=1` to retain successful MongoDB or Redis
resources. Each operator remains installed after its profile finishes.
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
unit suite and all seven integration profiles. The profiles share one Kind
cluster in the job. Tag publication does not run the tests again. A release tag
must point to a commit that passed the main-branch workflow.

## Cleanup

Delete only the dedicated cluster when the validation cycle is complete:

```bash
KUBECONFIG=/tmp/provider-datalab-it.kubeconfig \
  kind delete cluster --name provider-datalab-it
```

Platform setup creates a fresh disposable TLS certificate for `*.lab.acme.com`.

The pinned Educates controllers receive read-only CRD discovery permissions
from `manifests/educates-rbac.yaml` before startup. The harness checks both
controller rollouts before it creates a Datalab runtime. Controllers request
CPU and memory so they receive a CPU share under local load. Their health
probes allow five minutes for cold starts.
