# Dedicated Kind integration environment

This harness uses only the `provider-datalab-it` Kind cluster and the
`kind-provider-datalab-it` context. It stores that context in
`/tmp/provider-datalab-it.kubeconfig` by default. The scripts do not use the
default kubeconfig or another local cluster.

The setup follows the Provider Storage integration strategy:

- create or reuse one repository-specific Kind cluster;
- pass the kubeconfig and context to every cluster command;
- install Crossplane with automatic provider activation disabled;
- install explicit provider and function versions;
- wait for package health before creating test resources;
- keep cloud credentials outside this repository.

The harness tests with Crossplane `2.4.1` and Provider Storage `0.3.0`.
Crossplane `2.4.1` is a reproducible test pin, not the package's minimum
supported version. The harness reads the Provider Storage dependency manifests
from that Git tag in the adjacent `provider-storage` checkout. Set
`PROVIDER_STORAGE_REPO` if the checkout is elsewhere. The storage profiles do
not install Kyverno. The `verify-network` profile installs Kyverno because it
applies CEL policies.

Run the local render tests before cluster integration:

```bash
tests/unit.bash
```

The integration harness has three profiles. The `simple` profile installs only
the MinIO Provider Storage dependencies and creates storage for Jeff and Jane:

```bash
tests/integration/run.bash simple
```

The `complex` profile adds the AWS and OVHcloud dependencies, compositions,
and storage resources for Joe and John:

```bash
tests/integration/run.bash complex
```

The `verify-network` profile uses the same `provider-datalab-it` cluster and
runs the simple profile before it verifies NetworkPolicy and Kyverno behavior:

```bash
tests/integration/run.bash verify-network
```

This profile installs Kyverno `v1.19.1` with Helm chart `3.9.1`. Kind `v0.24.0`
or later provides NetworkPolicy enforcement through its default network
implementation, so the shared cluster does not need a second CNI. Successful
verification removes its temporary namespaces and policy. Failed verification
keeps them for diagnosis. Set `KEEP_NETWORK_RESOURCES=1` to keep successful
test resources. Each network check runs three times and writes timing results
to `/tmp/provider-datalab-network-verification.tsv`. Set `NETWORK_ITERATIONS`
or `NETWORK_RESULTS_FILE` to change these benchmark settings.

The complex profile requires the AWS and OVHcloud credentials and settings
described below. All profiles use the published MinIO package as the single
owner of the shared Storage API.

The platform phase installs the published MinIO Provider Storage configuration.
That package owns the shared `Storage` API. The AWS and OVHcloud packages are
also published, but each backend package contains the same `Storage` XRD.
Crossplane does not let more than one `ConfigurationRevision` control that
XRD. Installing the AWS or OVHcloud package beside MinIO makes the new revision
unhealthy with a `cannot establish control of object` error.

The harness therefore keeps MinIO as the single API owner. The complex profile
applies the AWS and OVHcloud compositions from the same immutable Git tag in
the adjacent checkout. This gives all three backends the exact `0.3.0`
source without conflicting XRD ownership. All profiles deploy the isolated
test MinIO instance. The fixed MinIO credentials are only for this disposable
cluster.

## Storage assignment

The test storage resources use this assignment:

| Datalab | Backend | EnvironmentConfig |
| --- | --- | --- |
| `s-joe` | AWS | `storage-aws` |
| `s-john` | OVHcloud | `storage-ovh` |
| `s-jeff` | MinIO | `storage-minio` |
| `s-jane` | MinIO | `storage-minio` |

Create the MinIO resources for Jeff and Jane:

```bash
tests/integration/deploy-storages.bash minio
```

Provider Storage writes the generated `s-jeff` and `s-jane` Secrets to the
`workspace` namespace. Provider Datalab reads the storage Secrets from that
same namespace.

## AWS for Joe

Create `workspace/aws-provider-creds` through your approved secret-management
path. The Secret must contain the `credentials` key expected by Provider
Storage. Do not commit the Secret.

Set the non-secret account settings and deploy Joe's storage:

```bash
export CROSSPLANE_AWS_ACCOUNT_ID=123456789012
export CROSSPLANE_AWS_REGION=eu-central-1
export CROSSPLANE_AWS_RUNTIME_ROLE_ARN=arn:aws:iam::123456789012:role/provider-storage/crossplane
tests/integration/deploy-storages.bash aws
```

The bucket name defaults to `datalab-<account-id>-s-joe`. Set
`CROSSPLANE_AWS_RESOURCE_PREFIX` when the account needs a different globally
unique prefix.

## OVHcloud for John

Create `workspace/ovh-provider-creds` through your approved secret-management
path. The Secret must contain the `credentials` key expected by Provider
Storage. Do not commit the Secret.

Set the non-secret project settings and deploy John's storage:

```bash
export CROSSPLANE_OVH_PROJECT_ID=0123456789abcdef0123456789abcdef
export CROSSPLANE_OVH_STORAGE_REGION=de
tests/integration/deploy-storages.bash ovh
```

Use `de` or `gra` for `CROSSPLANE_OVH_STORAGE_REGION`.

## Profile behavior

The simple profile is safe for pull-request automation because it uses only the
MinIO instance in the dedicated Kind cluster. The complex profile is for an
approved local run or a protected manual workflow because it creates external
cloud resources. The verify-network profile is a local security check. GitHub
Actions runs only the simple profile.

For a new local environment, run the simple profile first. Then add the AWS and
OVHcloud credential Secrets to its `workspace` namespace, set the non-secret
cloud values described above, and run the complex profile. The complex run is
idempotent and reuses the same dedicated cluster.

The harness reads Provider Storage dependency manifests from the exact Git tag
configured by `PROVIDER_STORAGE_VERSION`. In CI, check out that tag separately
and set `PROVIDER_STORAGE_REPO` to its path.

Delete only this dedicated cluster when the validation cycle is complete:

```bash
KUBECONFIG=/tmp/provider-datalab-it.kubeconfig \
  kind delete cluster --name provider-datalab-it
```
