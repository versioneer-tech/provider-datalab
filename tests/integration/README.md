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
| `verify-postgres` | `verify-postgres` from [manifests/postgres/datalab.yaml](manifests/postgres/datalab.yaml) | The Datalab requests PostgreSQL `pg0` with database `verify`, 1 GiB primary storage, and 1 GiB backup storage. The test uses the generated connection Secret for an internal SQL write and read. |

All Datalabs use a matching profile-named prerequisite Secret. They disable the
data component. Network and PostgreSQL Datalabs have no sessions. Each profile
removes its successful test resources. A failed profile keeps its resources
for diagnosis.

## Run profiles locally

Each command creates or reuses the dedicated cluster, deploys the common
platform, and runs one profile:

```bash
tests/integration/run.bash verify-network
tests/integration/run.bash verify-registry
tests/integration/run.bash verify-postgres
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

The PostgreSQL profile installs Crunchy PGO `6.0.1`, which is the version
pinned by EOEPCA+. Set `KEEP_POSTGRES_RESOURCES=1` to retain successful
resources. PGO remains installed after the profile finishes.

## GitHub Actions

Pull requests to `main`, pushes to `main`, and manual workflow runs execute the
unit suite and all three integration profiles. The profiles share one Kind
cluster in the job. Tag publication does not run the tests again. A release tag
must point to a commit that passed the main-branch workflow.

## Cleanup

Delete only the dedicated cluster when the validation cycle is complete:

```bash
KUBECONFIG=/tmp/provider-datalab-it.kubeconfig \
  kind delete cluster --name provider-datalab-it
```
