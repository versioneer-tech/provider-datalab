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
credentials, provider configuration, and storage. Workload Ingress and Gateway
synchronization is disabled. Use Kubernetes port forwarding to access a
workload Service.

Each group creates a profile Secret in the Datalab claim namespace. Its name
starts with `<datalab>-vcluster-<instance>-<group>`. Generated names have a stable
hash suffix when a component has a hyphen or the full name needs shortening. `status.connections` reports the instance, group, endpoint,
readiness, and Secret reference. It contains no credentials.

The Secret contains `kubeconfig`, `client-id`, `client-secret`, and `issuer-url`.
The kubeconfig uses Python 3 to obtain short-lived tokens. Export the required
profile and protect the file as a credential:

```bash
umask 077
profile_secret="$(kubectl -n workspace get datalab s-joe -o json | \
  jq -r '.status.connections[] | select(.instance == "vc0" and .group == "namespace-demo") | .secretRef.name')"
kubectl -n workspace get secret "${profile_secret}" \
  -o jsonpath='{.data.kubeconfig}' | base64 --decode > s-joe-vc0.kubeconfig
kubectl --kubeconfig ./s-joe-vc0.kubeconfig -n demo get pods
```

Roles are specific to an instance. A `vc0` profile does not authorize `vc1`.
The Datalab users group receives each instance's admin role. Additional namespace
profiles can use `view`, `edit`, or `admin`. Profile kubeconfigs use separate
service identities; the built-in profile provides virtual administration.
The provider keeps the recovery kubeconfig private.

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
profile boundaries, persistent volumes, and the catalog. The catalog test
creates a collection and item, searches it, restarts the API, and repeats the
search after a control-plane restart.

## Removal

Removing a group revokes its identity and binding while retaining its virtual
namespace data. Removing an instance removes its runtime and control-plane
PVC. Other instances, databases, sessions, and the shared namespace remain.
Deletion follows the host StorageClass retention policy. Back up control-plane
and database volumes before removing an instance or Datalab.
