# Connections and Secret bindings

The provider publishes connection metadata in `status.connections` and stores
credentials in separate Secrets in the Datalab claim namespace. It does not
create the combined `<datalab>-datalab` Secret.

| Connection | Secret | Keys |
| --- | --- | --- |
| `s3` | `<datalab>-s3` | AWS variables, `aws-credentials`, and rclone settings |
| `postgres-<store>` | `<datalab>-postgres-<store>` | `host`, `port`, `user`, `password`, `databases`, and `<database>_url` |
| `mongo-<store>` | `<datalab>-mongo-<store>` | `host`, `port`, `user`, `password`, `database`, `auth_source`, and `uri` |
| `redis-<store>` | `<datalab>-redis-<store>` | `host`, `port`, `user`, `password`, `database`, and `url` |
| `vcluster-<instance>-<profile>` | Read the exact name from status | `kubeconfig`, `client-id`, `client-secret`, and `issuer-url` |

Virtual profile Secret names can have a stable hash. Service keys use lower
case; S3 keeps its AWS key names. PostgreSQL external URLs use the
`<database>_url_external` key when a TLSRoute is configured.

For data services, `ready` reports whether the connection Secret is current.
Virtual profiles also require ready runtime, routing, RBAC, and identity
resources. Use Datalab and service conditions to check workload health. A
reference can exist before its Secret is ready.

When Data is enabled, `<datalab>-storage` supplies only storage credentials
in the service namespace. Its OAuth proxy uses `<datalab>-oauth2-client`.
Neither Secret contains database credentials. Database outputs are generated
independently of storage credentials. Backend permissions are unchanged: the
current PostgreSQL output uses the `postgres` account. Use a separate
application account when a workload needs limited database access. The
application's setup process owns that account and its grants.

## Approve an export

The operator defines `EnvironmentConfig.data.secretExports`. An export names
either a `secretRef` in the host cluster or a service `connection` from the
same Datalab. These source fields are mutually exclusive. Its `keys` list and
exact `targets` limit what each Datalab may request. There are no wildcard
targets and no exports by default.

```yaml
data:
  secretExports:
    analytics-reader:
      secretRef:
        namespace: workspace
        name: analytics-reader
      keys: [url]
      targets:
      - claimNamespace: workspace
        datalab: s-jane
        instance: vc0
        namespace: demo
```

The source can be in another host namespace. Provider Kubernetes needs read
access there. The observer uses `managementPolicies: [Observe]`; the binding
never writes to or deletes the host source. Keep export policy and the
selection of EnvironmentConfigs under platform authorization.

For a Datalab service output, replace `secretRef` with `connection: s3`,
`connection: postgres-pg0`, or another service connection name. Do not export
provider credentials, backup administration, main OAuth credentials, or
virtual API recovery credentials. Service-account token Secrets are rejected.

## Bind an export to a virtual namespace

Declare the binding beside the instance's access groups:

Each target key must occur once in the key map. The provider denies an
ambiguous map before it reads the source.

```yaml
spec:
  vclusters:
    vc0:
      groups:
      - name: readers
        namespace: demo
        role: view
      secretBindings:
        catalog-database:
          export: analytics-reader
          target:
            namespace: demo
            name: catalog-database
          keys:
            url: DATABASE_URL
```

This copies only the approved `url` key into `vc0/demo/catalog-database` as
`DATABASE_URL`. The provider creates the target namespace if needed and
retains that namespace when the binding is removed. General vcluster host
Secret import stays disabled. Bindings use the existing provider
configuration for the selected virtual API.

Target Secret names are reserved for their binding. A virtual admission
policy checks the ownership label before the target can be created, changed,
or deleted. It prevents adoption of an unrelated Secret at that name. Two
bindings cannot select the same instance, namespace, and Secret name.
Renaming a binding at the same destination waits for the old managed copy
to be removed before its replacement is created.

The target is a managed copy, not a protected reference to the host object.
Virtual RBAC controls access to it. Reconciliation restores its selected data;
it does not prevent a virtual administrator from changing the virtual
cluster's RBAC or admission policy. Mount credentials read-only when using
files. Database or storage read-only access still requires a backend account
with those permissions.

## Check delivery and rotation

`status.secretBindings` records each binding's instance, export, target,
`ready` value, and reason. `SecretBindingsReady` summarizes these entries.
Status contains no credential values. A denied export reads no source Secret.

A binding waits for the source, required keys, and virtual admission policy.
It reports ready after the target Secret has the current data. Source changes
update only the selected keys. A source outage preserves the last managed
copy and reports not ready. Missing keys do not create an empty Secret.

Removing a binding or revoking its export removes its managed copy and source
observer. It leaves the source, namespace, application data, and other
instances intact. Deleting a copy cannot revoke values already read by a
workload: revoke the backend identity when access must end. Applications must
reload changed files or restart; environment variables do not update in a
running process.

## Access control

API clients should list authorized metadata by default and resolve credentials
only on an explicit request. An `include-secret` parameter grants no permission:
authorize every connection and use `Cache-Control: no-store` for credential
responses. Resolve only provider-published references.

Restrict access to claim namespace Secrets and provider Object resources.
The latter can contain credential values in their specs and observed state.
A virtual administrator can read all Secrets in that virtual cluster. A user
who can create Pods in a namespace can usually mount that namespace's Secrets.
See [ADR-003](../architecture/0003-isolate-teams-and-bind-service-secrets.md).
