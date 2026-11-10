# Connections and Secret bindings

The provider publishes connection metadata in `status.connections`. Credentials
remain in the referenced Secrets.

| Type | Name | Credentials |
| --- | --- | --- |
| `s3` | `primary` | Storage source Secret; AWS keys and optional session token |
| `postgres` | Store name | Published operator fields: `host`, `port`, `user`, `password`, `dbname`, and `uri` |
| `mongo` | Store name | Published `user` and `password` |
| `redis` | Store name | Published `user` and `password` |
| `registry` | `primary` | Published `user` and `password` |
| `custom` | Configured Secret name | Published source keys and usable Secret type |
| `vcluster` | Instance and profile | Public `kubeconfig`, `client-id`, and `issuer-url` |

Read each exact Secret name and namespace from `status.connections[].secretRef`.
Managed service and custom connections wait until their published copy matches
the source. S3 readiness reports source observation. Virtual profiles also
require ready runtime, routing, RBAC, and identity resources. These checks do
not report Secret delivery into a virtual cluster.

Separate normalized outputs remain available in the claim namespace as
`<datalab>-s3`, `<datalab>-postgres-<store>`, `<datalab>-mongo-<store>`, and
`<datalab>-redis-<store>`. They supply the host, URI, and storage fields used by
the service examples. Use the status reference for native Secret bindings.

When Data or the registry is enabled, `<datalab>-storage` supplies only storage
credentials in the service namespace. Public Data and S3 proxies use a separate
`<datalab>-oauth2-client` Secret. Neither runtime Secret contains database
credentials. Database outputs are generated independently of storage access.
The PostgreSQL output uses the `postgres` account. Application setup owns
accounts and grants when a workload needs less access.

## Bind a connection

Use `spec.vclusters.<instance>.secretBindings` as a list of `type`, `name`,
and `target` entries. Available service types are `s3`, `postgres`, `mongo`,
`redis`, and `registry`. The operator can list predefined host Secrets in
`EnvironmentConfig.data.customSecrets` for `custom` connections.

Bindings use ready source references from `status.connections`. The native
vCluster sync creates the target namespace and copies the whole Secret with
its original data keys. Source updates and deletion pass through the sync.
Missing optional custom Secrets are omitted from status and do not block
readiness. Ambiguous source or target mappings are omitted.

See [Secret bindings](vcluster.md#secret-bindings) for source names, operator
settings, and examples. Applications must reload changed files or restart;
environment variables do not update in a running process. Revoke the backend
identity when access must end.

## Access control

API clients should list authorized metadata by default and resolve credentials
only on an explicit request. An `include-secret` parameter grants no permission:
authorize every connection and use `Cache-Control: no-store` for credential
responses. Resolve only provider-published references.

Restrict access to claim namespace Secrets and provider Object resources.
The latter can contain credential values in their specs and observed state.
A virtual administrator can read all Secrets in that virtual cluster. A user
who can create Pods in a namespace can usually mount that namespace's Secrets.
