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
| `verify-network` | `verify-network-open` and `verify-network-closed` from [manifests/network/datalabs.yaml](manifests/network/datalabs.yaml) | The closed Datalab disables external egress and vCluster access. The open Datalab enables both. The test applies their generated NetworkPolicies and verifies namespace isolation, DNS, MinIO, metadata, vCluster, and external access. |
| `verify-registry` | `verify-registry` from [manifests/registry/datalab.yaml](manifests/registry/datalab.yaml) | The Datalab starts one session with a 1 GiB registry. The test authenticates to the session registry and writes and reads a blob. |
| `verify-data` | `verify-data-enabled` and `verify-data-disabled` from [manifests/data/datalabs.yaml](manifests/data/datalabs.yaml) | The test verifies one provider-owned package-r Deployment and Service, restricted ingress and DNS NetworkPolicies, the vnext runtime contract, credential rotation, S3 bucket discovery, no CSI-backed Data PVC, stable Data ingress configuration, and complete omission when Data is disabled. |
| `verify-postgres` | `verify-postgres` from [manifests/postgres/datalab.yaml](manifests/postgres/datalab.yaml) | The Datalab requests PostgreSQL `pg0` with database `verify`, 1 GiB primary storage, and 1 GiB backup storage. The test uses the generated connection Secret for an internal SQL write and read. |
| `verify-mongo` | `verify-mongo` from [manifests/mongo/datalab.yaml](manifests/mongo/datalab.yaml) | The Datalab requests the `verify` MongoDB document store. The test uses the generated connection Secret for an internal document write and read. |
| `verify-redis` | `verify-redis` from [manifests/redis/datalab.yaml](manifests/redis/datalab.yaml) | The Datalab requests the `verify` Redis cache store. The test uses the generated connection Secret for an internal key write and read. |
| `verify-qdrant` | `verify-qdrant` from [manifests/qdrant/datalab.yaml](manifests/qdrant/datalab.yaml) | The Datalab requests the `verify` Qdrant vector store. The test uses the generated connection Secret to create a collection and write and read a point. |

All Datalabs use a matching profile-named prerequisite Secret. Only the enabled
Data fixture enables the Data component, and only the registry fixture starts a
session. Each profile removes its successful test resources. A failed profile
keeps its resources for diagnosis.

## Run profiles locally

Each command creates or reuses the dedicated cluster, deploys the common
platform, and runs one profile:

```bash
tests/integration/run.bash verify-network
tests/integration/run.bash verify-registry
tests/integration/run.bash verify-data
tests/integration/run.bash verify-postgres
tests/integration/run.bash verify-mongo
tests/integration/run.bash verify-redis
tests/integration/run.bash verify-qdrant
```

The network profile installs Kyverno `1.19.1` with chart `3.9.1` because it
tests a CEL admission policy. Kind `0.24.0` or later provides NetworkPolicy
enforcement through its default network implementation. Set
`KEEP_NETWORK_RESOURCES=1` to retain successful resources. Each network check
runs three times and writes timings to
`/tmp/verify-network.tsv`.

The registry profile installs Kyverno because the Educates runtime applies
Kyverno policies. It then installs the EOEPCA+ Educates dependency chart
`2.2.1`, which contains Educates `3.7.1`. Set `KEEP_REGISTRY_RESOURCES=1` to
retain successful resources.

The Data profile reuses the same Educates installation. It checks both the
provider-kubernetes wrapper objects and the target resources in the runtime
namespace. Set `KEEP_DATA_RESOURCES=1` to retain successful resources.

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
