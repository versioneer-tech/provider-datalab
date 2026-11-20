# Connections and Secret bindings

The provider publishes connection metadata in `status.connections`. Credentials
remain in the referenced Secrets.

| Type | Name | Secret contents |
| --- | --- | --- |
| `s3` | `primary` | Storage source Secret; AWS keys and optional session token |
| `postgres` | Store name | `host`, `port`, `user`, `password`, `dbname`, and `uri` |
| `mongo` | Store name | `user` and `password` |
| `redis` | Store name | `user` and `password` |
| `registry` | `primary` | `user` and `password` |
| `custom` | Configured Secret name | Source data and usable Secret type |
| `vcluster` | Instance and profile | Public `kubeconfig`, `client-id`, and `issuer-url` |

Read the Secret name and namespace from `status.connections[].secretRef`.
Managed service and custom connections wait until their published copy matches
the source. S3 requires a current source Secret and a ready observer. Virtual
profiles require ready runtime, routing, RBAC, and identity resources.
Connection readiness does not confirm Secret delivery into a virtual cluster.

The service examples use additional Secrets in the Datalab namespace:
`<datalab>-s3`, `<datalab>-postgres-<store>`, `<datalab>-mongo-<store>`, and
`<datalab>-redis-<store>`. They supply host, URI, and storage fields.
For bindings, use the Secret reference in status.

When Data or the registry is enabled, `<datalab>-storage` supplies only storage
credentials in the service namespace. Public Data and S3 proxies use a separate
`<datalab>-oauth2-client` Secret. Neither runtime Secret contains database
credentials. Database outputs are generated independently of storage access.
PostgreSQL credentials use the `postgres` account. Create application accounts
and grants when a workload needs less access.

## Bind a connection

Use `spec.vclusters.<instance>.secretBindings` as a list of `type`, `name`,
and `target` entries. Available service types are `s3`, `postgres`, `mongo`,
`redis`, and `registry`. The operator can list predefined host Secrets in
`EnvironmentConfig.data.customSecrets` for `custom` connections.

Bindings use ready source references from `status.connections`. vCluster creates
the target namespace and copies the whole Secret with its original data keys.
It applies source updates and deletion to the copy.
Missing optional custom Secrets are omitted from status and do not block
readiness. Ambiguous source or target mappings are omitted.

See [Secret bindings](vcluster.md#secret-bindings) for source names, operator
settings, and examples. Applications must reload changed files or restart;
environment variables do not update in a running process. Revoke the backend
identity when access must end.

## Access control

Restrict access to Secrets and provider Object resources. Object specs can
contain generated credentials; status redaction does not remove values from
specs or Secret annotations.

The supplied provider-kubernetes runtime enables `--sanitize-secrets`. The
composition reads source Secrets through Crossplane's required-resource API,
so it does not depend on credential values in Object status.

A virtual administrator can read all Secrets in that virtual cluster. A user
who can create Pods in a namespace can usually mount that namespace's Secrets.
