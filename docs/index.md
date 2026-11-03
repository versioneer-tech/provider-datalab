# Provider Datalab

Provider Datalab creates shared data workspaces on Kubernetes. Teams declare
users, storage access, virtual clusters, and managed services in a `Datalab` resource. Crossplane
creates the resources from the platform's EnvironmentConfig.

The shared Data service, packageR, provides object-storage browsing and file
sharing. Datalabs can also request PostgreSQL, MongoDB, and Redis.

| Task | Guide |
| --- | --- |
| Prepare the platform | [Installation and EnvironmentConfig reference](how-to-guides/installation.md) |
| Use stores, virtual clusters, and shared files | [Use a Datalab](how-to-guides/usage_concepts.md) |
| Protect browser and machine access | [Authentication](how-to-guides/authentication.md) |
| Read data with AWS tools | [S3 client access](how-to-guides/s3-access.md) |
| Run Dask, MLflow, or psql | [Additional services](how-to-guides/additional_services.md) |
| Deliver selected service credentials | [Connections and Secret bindings](how-to-guides/connections.md) |
| Review access controls | [Security](security/index.md) |
| Look up Datalab fields | [API reference](reference-guides/api.md) |

[ADR-001](architecture/0001-use-the-datalab-crd-as-the-workspace-contract.md)
records why Datalab is the public API and runtime resources stay internal.
[ADR-002](architecture/0002-provide-managed-database-services.md) records why
PostgreSQL, MongoDB, and Redis are managed services and how users and the
platform operator share responsibility.

[ADR-003](architecture/0003-isolate-teams-and-bind-service-secrets.md) records
team virtual cluster boundaries and approved Secret delivery.
