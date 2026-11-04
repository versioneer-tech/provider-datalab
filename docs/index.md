# Provider Datalab

A `Datalab` gives a team virtual Kubernetes APIs, shared data, and managed
databases through one resource. Crossplane provisions them from the platform's
EnvironmentConfig. Optional browser sessions provide editors and terminals
alongside those services.

| Task | Guide |
| --- | --- |
| Prepare the platform | [Installation and EnvironmentConfig reference](how-to-guides/installation.md) |
| Run Kubernetes workloads and bind service Secrets | [Virtual clusters](how-to-guides/vcluster.md) |
| Protect browser and machine access | [Authentication](how-to-guides/authentication.md) |
| Use stores, share files, and start browser sessions | [Use a Datalab](how-to-guides/usage_concepts.md) |
| Read data with AWS tools | [S3 client access](how-to-guides/s3-access.md) |
| Run Dask, MLflow, or psql | [Additional services](how-to-guides/additional_services.md) |
| Review access controls | [Security](security/index.md) |
| Look up Datalab fields | [API reference](reference-guides/api.md) |

[ADR-001](architecture/0001-use-the-datalab-crd-as-the-workspace-contract.md)
records why Datalab is the public API and runtime resources stay internal.
[ADR-002](architecture/0002-provide-managed-database-services.md) records why
PostgreSQL, MongoDB, and Redis are managed services and how users and the
platform operator share responsibility.
