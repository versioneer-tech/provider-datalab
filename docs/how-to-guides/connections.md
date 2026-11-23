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

## Bind a connection

Select a ready `status.connections` entry by `type` and `name`. Add it to
`spec.vclusters.<instance>.secretBindings` with a target namespace and Secret
name. Available service types are `s3`, `postgres`, `mongo`, `redis`, and
`registry`. Only declared service instances can be selected.

```yaml
spec:
  databases:
    pg0:
      names: [analytics]
      storage: 5Gi
  vclusters:
    vc0:
      secretBindings:
      - type: postgres
        name: pg0
        target:
          namespace: applications
          name: database-credentials
```

The mapping uses the selected connection's `secretRef`. vCluster creates the
target namespace and copies the whole Secret with its original data keys.
It applies source updates and deletion to the copy. Only ready, unambiguous
connections generate mappings; reconciliation removes mappings that are no
longer ready. Check that the target Secret exists before starting the application.

Applications must reload changed files or restart; environment variables do
not update in a running process. Revoke the backend identity when access must end.

### Custom connections

The operator can list predefined host Secrets in
`EnvironmentConfig.data.customSecrets`:

```yaml
data:
  customSecrets:
  - name: application-key
  - name: shared-key
    namespace: platform-secrets
```

Without `namespace`, the provider checks the Datalab's runtime namespace.
Names must be unique. It observes the source without changing it. Missing
optional sources are omitted from status and do not block Datalab readiness.
An available source is listed with `ready: false` until its published copy is
current. Bind it with the same API:

```yaml
spec:
  vclusters:
    vc0:
      secretBindings:
      - type: custom
        name: application-key
        target:
          namespace: applications
          name: application-credentials
```

See [Credential access in SECURITY.md](https://github.com/versioneer-tech/provider-datalab/blob/main/SECURITY.md#credential-access)
for Secret permissions, administrative database accounts, and provider Object access.
