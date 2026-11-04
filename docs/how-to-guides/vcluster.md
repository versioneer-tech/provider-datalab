# Use a Datalab virtual cluster

Declare each virtual Kubernetes cluster under `spec.vclusters`:

```yaml
apiVersion: pkg.internal/v1beta2
kind: Datalab
metadata:
  name: s-joe
  namespace: workspace
spec:
  users: [joe]
  vclusters:
    vc0:
      storage: 5Gi
      groups:
      - name: namespace-demo
        namespace: demo
        role: edit
```

Each entry creates one runtime in the Datalab namespace. Add
`vc1` alongside `vc0` to create another cluster. An empty map creates none.
Sessions and their environment-controlled vclusters remain separate.

Each instance includes a built-in `cluster-admin` profile. All users in
`spec.users` receive `vcluster_<instance>_cluster-admin` through the Datalab
users group. The role belongs to that Datalab's Keycloak client. `groups` is optional and defines additional profiles.

## Platform settings

Merge these values into the Datalab's EnvironmentConfig:

```yaml
data:
  iam:
    issuerURL: https://identity.example.org/realms/datalab
  ingress:
    domain: lab.acme.com
  httpRoute:
    enabled: true
    parentName: datalab
    parentNamespace: gateway-system
    sectionName: https
  vcluster:
    storage: 5Gi
    storageClasses:
      allowed: [standard]
      default: standard
```

The `vcluster` EnvironmentConfig section supplies defaults for all declared
instances. `spec.vclusters.<name>.storage` overrides the control-plane PVC size.
`vcluster.storageClassName` selects its class; otherwise the default class is
used. Only classes in `vcluster.storageClasses.allowed` are exposed to virtual
workloads. A host admission policy enforces this list for each syncer.
Control-plane, workload, database, and session PVCs share the existing
`defaults.overallQuota.storage` limit.

Set `vcluster.resources.requests` and `vcluster.resources.limits` in the
EnvironmentConfig to change control-plane resources. Both the native vCluster
configuration and the host StatefulSet use these values. The defaults are CPU
`200m` and memory `1Gi` for requests, and CPU `4` and memory `4Gi` for limits.
Ephemeral storage defaults to a `1Gi` request and a `10Gi` limit. Each supplied
field overrides its default.

For the tested two-connection SQLite settings, merge:

```yaml
data:
  vcluster:
    backingStore:
      database:
        embedded:
          enabled: true
          dataSource: "sqlite:///data/state.db?_journal=TRUNCATE&_locking=NORMAL&cache=shared&_busy_timeout=30000&_txlock=immediate&_synchronous=FULL"
          extraArgs:
          - --datastore-max-open-connections=2
          - --datastore-max-idle-connections=1
```

Apply `dependencies/rbac.yaml`. The host must serve
`ValidatingAdmissionPolicy` and `ValidatingAdmissionPolicyBinding`. The Gateway
must support HTTPRoute prefix rewriting, BackendTLSPolicy, and Kubernetes
streaming requests. `vcluster.backendTLS.apiVersion` defaults to
`gateway.networking.k8s.io/v1`; set it to the version served by your platform.

Set `network.serviceCIDR` and `network.podCIDRs` to the host ranges. Virtual
workloads follow the environment's network policy. Managed databases in the
same runtime namespace are reachable through their generated connection
endpoints. Cross-namespace backends need an approved `network.internalEgress`
rule. Virtual clusters share the host namespace and node kernel; their RBAC
boundaries apply to their virtual APIs.

## Secret bindings

Select a Datalab connection by type and instance name:

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

The provider
publishes each service connection in `status.connections`, with its `type`,
`name`, `secretRef`, and source readiness. A binding selects the same `type`
and `name` pair. The mapping uses that connection's `secretRef`.

The connection sources are:

| Type | Name | Host Secret |
| --- | --- | --- |
| `s3` | `primary` | The Secret with the same name as the Datalab |
| `postgres` | A key in `spec.databases` | `<name>-pguser-postgres` in the runtime namespace |
| `mongo` | A key in `spec.documentStores` | `<name>-mongodb-auth` in the runtime namespace |
| `redis` | A key in `spec.cacheStores` | `<name>-redis-auth` in the runtime namespace |
| `custom` | A predefined Secret name | The named Secret in the team's runtime namespace, or its configured namespace |

Only declared service instances can be selected. The storage source namespace
comes from `EnvironmentConfig.data.storage.secretNamespace`, or the claim
namespace when unset. Use a custom connection for credentials such as a GitHub token.

The operator can list predefined custom Secrets in the EnvironmentConfig:

```yaml
data:
  customSecrets:
  - name: apikey-1
  - name: apikey-2
```

The provider checks these names in each Datalab's runtime namespace. Set
`namespace` on an entry to use a shared source namespace. Names must be unique.
It observes the source and does not create or change it. A custom connection
is listed in `status.connections` only after its source is confirmed ready.
The examples give `s-john` both keys and `s-jane` only `apikey-1`.
Status lists the keys present in each team namespace. Missing custom sources
do not block Datalab readiness.

Bind an available custom connection through the same list:

```yaml
spec:
  vclusters:
    vc0:
      secretBindings:
      - type: custom
        name: apikey-1
        target:
          namespace: applications
          name: application-credentials
```

vCluster creates the virtual namespace and syncs the whole Secret, including
source updates and deletion. Only connections with `ready: true` generate native mappings. Unknown or
unready references are skipped. A later reconciliation adds the mapping when
the connection is ready. If readiness is lost, its mapping is removed from
the generated configuration. Datalab readiness requires all published connections
to be ready and the existing resource checks to pass.

## API access

The generated kubeconfig for `vc0` uses:

```text
https://s-joe.lab.acme.com/.vc0
```

The Gateway removes `/.vc0` and forwards to that instance. A separate backend
TLS policy verifies its certificate. Each instance has its own selectors,
provider configuration, and storage. Workload Ingress and Gateway
synchronization is disabled. Use Kubernetes port forwarding to access a
workload Service.

Each group creates a profile Secret in the Datalab claim namespace.
`status.connections` reports the instance, group, endpoint, readiness, and
Secret reference. Resolve the reference from status; do not construct its name.
The Secret contains only `kubeconfig`, the public `client-id`, and `issuer-url`.
The kubeconfig can include public CA certificates. It contains no client secret,
access token, refresh token, private key, or client certificate.

A profile selects the endpoint and default namespace. It does not select an
identity or grant permissions. Downloading `cluster-admin` does not give the
caller that role. Every profile uses the existing Datalab client, such as
`ws-alice`. The API checks the authenticated caller's token roles, issuer,
Datalab audience, signature, and expiry. Kubernetes RBAC controls access.
Roles are specific to an instance. A token needs a configured role for each
instance it uses. A namespace default cannot restrict a token with wider grants.

The Datalab users group receives each instance's admin role. Additional
namespace profiles can bind `view`, `edit`, or `admin`. An identity administrator
must assign these roles to the intended human or machine identity. Scope
mappings allow assigned roles in workspace tokens; they do not grant roles.
The workspace service account has only `ws_api` by default. Its token fails
virtual API authentication until a vcluster role is explicitly assigned.
The provider keeps the recovery kubeconfig private.

`ready: true` reports runtime, routing, role, scope, and RBAC readiness. It does
not imply caller authorization or require a caller credential to be present.
Workspace API Secret-download permissions are unchanged. Access to database,
registry, OAuth2, or other service Secrets requires a separate authorization
decision.

Download a profile:

```bash
umask 077
profile_secret="$(kubectl -n workspace get datalab s-joe -o json | \
  jq -r '.status.connections[] | select(.instance == "vc0" and .group == "namespace-demo") | .secretRef.name')"
kubectl -n workspace get secret "${profile_secret}" \
  -o jsonpath='{.data.kubeconfig}' | base64 --decode > s-joe-vc0.kubeconfig
```

### Human access

Use the platform's browser OAuth2 authorization-code login to obtain an access
token for your human identity. Request the Datalab audience and ensure that
the token includes your assigned roles under
`resource_access.<datalab>.roles`. Use an access token, not an ID token. Save it
to a private file through the platform's login tool. Set its path for the
kubeconfig helper:

```bash
export DATALAB_ACCESS_TOKEN_FILE="$HOME/.config/datalab/access-token"
chmod 600 "$DATALAB_ACCESS_TOKEN_FILE"
kubectl --kubeconfig ./s-joe-vc0.kubeconfig -n demo get pods
```

The helper reads this file and uses your token without an identity exchange.
Renew the file through the same login flow when the token expires.

### Machine access

An identity administrator must first assign the required
`vcluster_<instance>_<group>` role to the existing workspace service account.
For example, `vcluster_vc0_namespace-demo` permits the configured operations
in `demo`; it does not grant virtual cluster administration. This assignment
is outside the composition. Do not add the account to the Datalab users group,
which grants virtual cluster administration.

Obtain the existing workspace client secret from `<datalab>-oauth-client`
through an authorized Secret-delivery process. Store the decoded client secret
alone in a private file, outside the profile and repository. Use one credential
source at a time:

```bash
unset DATALAB_ACCESS_TOKEN_FILE
export DATALAB_CLIENT_SECRET_FILE="$HOME/.config/datalab/client-secret"
chmod 600 "$DATALAB_CLIENT_SECRET_FILE"
kubectl --kubeconfig ./s-joe-vc0.kubeconfig -n demo get pods
```

The Python 3 helper exchanges this secret for a short-lived token with
`grant_type=client_credentials`. It uses the public workspace client ID and
issuer from the profile. Every profile then has the same machine identity and
its explicitly assigned roles. Removing a role affects new tokens; existing
tokens keep their claims until expiry unless the API's configured role or
binding is removed.

For a private issuer CA, set `vcluster.issuerCA`. An optional HTTPS
`vcluster.discoveryURL` can provide separate discovery routing with the same
issuer. For a private Gateway CA, set `ingress.certificateAuthority`.

## Datalab STAC catalog

The [STAC workload example](https://github.com/versioneer-tech/provider-datalab/blob/main/examples/vcluster/stac-fastapi.yaml)
runs `stac-fastapi-pgstac` in virtual namespace `demo`. Its PostgreSQL database
is a Datalab-managed service on the host. Add this request alongside `vclusters`:

```yaml
databases:
  pg0:
    type: postgres
    names: [catalog]
    storage: 5Gi
```

[PgSTAC](https://stac-utils.github.io/pgstac/pgstac/) requires PostGIS and a schema
migration. The example migration Job uses the generated PostgreSQL credentials
from the Datalab Secret. It creates a separate `catalog` login with the
`pgstac_ingest` role. The API uses that login and the standard
[PostgreSQL settings](https://stac-utils.github.io/stac-fastapi-pgstac/settings/):
`PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD`, and `PGDATABASE`.

PostgreSQL needs DNS and access to the host Kubernetes API for its controller.
In a namespace with denied egress, approve these targets for the PostgreSQL
Pods. Namespace selectors do not match host-network API endpoints on all CNIs.
The integration has a PostgreSQL-specific policy for this case.

The example expects `catalog-postgres-admin` and `catalog-postgres` Secrets in
virtual namespace `demo`. The first contains migration credentials. The second
contains the API login. Supply these through your Secret process. Build the
image from `tests/vcluster/catalog.Dockerfile`, push it to your registry, and
replace `__CATALOG_IMAGE__` with that image reference before applying the example.
Wait for `catalog-migrate` to complete before starting the API Deployment.
Remove the migration Secret after it completes.

Connect to the catalog through the generated profile:

```bash
kubectl --kubeconfig ./s-joe-vc0.kubeconfig -n demo \
  port-forward service/catalog 8080:8080
```

The catalog is available at `http://localhost:8080`. The example enables STAC
transactions so a client can add collections and items. Its catalog records
remain in PostgreSQL when the API Pod restarts.

Run `tests/integration/run.bash verify-vcluster` to check both virtual clusters,
caller role boundaries, credential-free profiles, persistent volumes, and the catalog. The catalog test
creates a collection and item, searches it, restarts the API, and repeats the
search after a control-plane restart.

## Removal

Removing a group removes its role and binding while retaining its virtual
namespace data. Removing an instance removes its runtime and control-plane
PVC. Other instances, databases, sessions, and the shared namespace remain.
Deletion follows the host StorageClass retention policy. Back up control-plane
and database volumes before removing an instance or Datalab.

## Upgrade from profile clients

The new composition removes profile clients, their service-account role
assignments, profile audience mappers, obsolete scope mappings, and credential
observers. It retains vcluster role definitions, human grants, audience checks,
and Kubernetes RBAC. The workspace service account receives no new grant.

Profile connection Secrets have new names. Crossplane deletes the old composed
Secrets and creates public connection Secrets. Resolve the new names from
`status.connections` and download the profiles again. New names prevent old
credential data from remaining in an updated Secret. No workspace credential
is copied into these Secrets.

Check that the old managed clients and their Keycloak clients are deleted.
Their service accounts are removed with them. Previously downloaded profile
client secrets must no longer obtain tokens. Deleting only a Kubernetes Secret
does not revoke a Keycloak credential. Check old `<profile>-oauth` Secrets too:
provider-owned Secrets are garbage collected with their managed Client. If a
Secret was copied or has no owner, remove it through the platform's Secret
process after confirming that its client is gone. Do not remove the shared
`<datalab>-oauth-client` Secret or workspace client.

Already-issued JWTs can remain valid until expiry because the virtual API
validates them locally. Allow that lifetime to pass before declaring old-token
access revoked, or remove the affected role or binding to deny access sooner.
The old downloaded client credentials cannot renew those tokens after client
deletion. Restore required machine access only through an explicit workspace
service-account role grant.
