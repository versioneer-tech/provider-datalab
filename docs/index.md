# Provider Datalab

Provider Datalab creates shared data workspaces on Kubernetes. Teams declare
users, sessions, and managed services in a `Datalab` resource. Crossplane
creates the resources from the platform's EnvironmentConfig.

Educates provides session editors, terminals, and persistent workspaces.
The shared Data service, packageR, provides object-storage browsing and file
sharing. Datalabs can also request PostgreSQL, MongoDB, Redis, and Qdrant.

| Task | Guide |
| --- | --- |
| Prepare the platform | [Installation and EnvironmentConfig reference](how-to-guides/installation.md) |
| Manage sessions, stores, and shared files | [Use a Datalab](how-to-guides/usage_concepts.md) |
| Protect browser and machine access | [Authentication](how-to-guides/authentication.md) |
| Read data with AWS tools | [S3 client access](how-to-guides/s3-access.md) |
| Run Dask, MLflow, or psql | [Additional services](how-to-guides/additional_services.md) |
| Review access controls | [Security](security/index.md) |
| Look up Datalab fields | [API reference](reference-guides/api.md) |

[ADR-001](architecture/0001-use-the-datalab-crd-as-the-workspace-contract.md)
records why Datalab is the public API and Educates is the internal runtime.
