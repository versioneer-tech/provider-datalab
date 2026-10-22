# Dedicated Kind integration environment

The integration tests use only the `provider-datalab-it` Kind cluster and the
`kind-provider-datalab-it` context. The default kubeconfig is
`/tmp/provider-datalab-it.kubeconfig`. The scripts do not use another local
cluster or the default kubeconfig.

The harness tests Provider Datalab behavior. It does not install or test
Provider Storage. It creates fixed profile-named Secrets for the disposable
in-cluster MinIO service because the Datalab composition needs object-storage
credentials.

Crossplane `2.4.1` is the reproducible test pin. Provider Datalab supports
Crossplane v2 or later.

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
| `verify-postgres` | `verify-postgres` from [manifests/postgres/datalab.yaml](manifests/postgres/datalab.yaml) | The Datalab requests PostgreSQL `pg0` with database `verify`, 1 GiB primary storage, and 1 GiB backup storage. The test uses the generated connection Secret for an internal SQL write and read. |
| `verify-mongo` | `verify-mongo` from [manifests/mongo/datalab.yaml](manifests/mongo/datalab.yaml) | The Datalab requests the `verify` MongoDB document store. The test uses the generated connection Secret for an internal document write and read. |
| `verify-redis` | `verify-redis` from [manifests/redis/datalab.yaml](manifests/redis/datalab.yaml) | The Datalab requests the `verify` Redis cache store. The test uses the generated connection Secret for an internal key write and read. |
| `verify-qdrant` | `verify-qdrant` from [manifests/qdrant/datalab.yaml](manifests/qdrant/datalab.yaml) | The Datalab requests the `verify` Qdrant vector store. The test uses the generated connection Secret to create a collection and write and read a point. |

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
tests/integration/run.bash verify-qdrant
```

The network profile uses controlled HTTP targets to test generated policies.
It does not start a real vCluster or test admission policy. Each connection
check runs once after the policies have converged. Set
`KEEP_NETWORK_RESOURCES=1` to retain successful resources.

The registry profile installs Kyverno because the Educates runtime applies
Kyverno policies. It then installs the EOEPCA+ Educates dependency chart
`2.2.1`, which contains Educates `3.7.1`. Set `KEEP_REGISTRY_RESOURCES=1` to
retain successful resources.

The Data profile reuses the Educates installation and seeds one disposable
MinIO bucket for file operations. It tests access through the runtime Service.
Set `KEEP_DATA_RESOURCES=1` to retain successful resources.

The S3 profile enables `httpRoute.enableS3` in its EnvironmentConfig.
It adds Contour, Keycloak, and an SDK client to test
[S3 client access](../../docs/how-to-guides/usage_concepts.md#s3-client-access).
The boto3 client uses `s3-credentials.py` as its AWS `credential_process`.
The test Pod receives `CLIENT_SECRET` from the generated Datalab OAuth Secret.
Set `KEEP_S3_RESOURCES=1` to retain successful resources.

The PostgreSQL profile installs Crunchy PGO `6.0.1`, which is the version
pinned by EOEPCA+. Set `KEEP_POSTGRES_RESOURCES=1` to retain successful
resources. PGO remains installed after the profile finishes.

The managed-store profiles use operator releases that accept the CR shape
emitted by the composition:

- MongoDB Kubernetes Operator chart `1.12.0` serves
  `mongodbcommunity.mongodb.com/v1`.
- Redis Operator chart `0.26.1`, with operator `0.26.0`, serves
  `redis.redis.opstreelabs.in/v1beta2`.
- Qdrant Operator `0.0.3` serves `qdrant.io/v1alpha1`. Its newer development
  line uses a different API group, so it is not compatible with the current
  composition.

Set `KEEP_STORE_RESOURCES=1` to retain successful MongoDB, Redis, or Qdrant
resources. Each operator remains installed after its profile finishes.

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

The pinned Educates controllers receive read-only CRD discovery permissions
from `manifests/educates-rbac.yaml` before startup. The harness checks both
controller rollouts before it creates a Datalab runtime. Controllers request CPU and memory so they receive a CPU share under local
load. Their health probes allow five minutes for cold starts.
