# Use a Datalab virtual cluster

Declare each virtual Kubernetes cluster under `spec.vclusters`:

```yaml
apiVersion: pkg.internal/v1
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
      - name: cluster-admin
        namespace: "*"
        role: cluster-admin
```

Each entry creates one runtime in the Datalab namespace. Add
`vc1` alongside `vc0` to create another cluster. An empty map creates none.

[ADR-003](../architecture/0003-isolate-teams-and-bind-service-secrets.md)
describes one Datalab per team, one virtual cluster by default when needed,
and explicit service Secret bindings for application namespaces. See
[connection bindings](connections.md#bind-an-export-to-a-virtual-namespace).

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
Control-plane, workload, and database PVCs share the existing
`defaults.overallQuota.storage` limit.

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
Workspace roles alone do not authorize either virtual API. Namespace profiles
can use `view`, `edit`, or `admin`. Use `namespace: "*"` with `cluster-admin`
for virtual administration. The provider keeps the recovery kubeconfig private.

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
from the separate PostgreSQL connection. It creates a separate `catalog` login with the
`pgstac_ingest` role. The API uses that login and the standard
[PostgreSQL settings](https://stac-utils.github.io/stac-fastapi-pgstac/settings/):
`PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD`, and `PGDATABASE`.

PostgreSQL needs DNS and access to the host Kubernetes API for its controller.
In a namespace with denied egress, approve these targets for the PostgreSQL
Pods. Namespace selectors do not match host-network API endpoints on all CNIs.
The integration has a PostgreSQL-specific policy for this case.

The example expects `catalog-postgres-admin` and `catalog-postgres` Secrets in
virtual namespace `demo`. The first contains migration credentials. The second
contains the API login. Use an operator-approved
[Secret binding](connections.md#bind-an-export-to-a-virtual-namespace) to
deliver the required keys into `vc0/demo`. The integration example binds
`postgres-pg0` for migration; application credentials must use a suitable
backend account. Build the image from `tests/vcluster/catalog.Dockerfile`, push it to your registry, and
replace `__CATALOG_IMAGE__` with that image reference before applying the example.
Wait for `catalog-migrate` to complete before starting the API Deployment.
Remove the migration binding after it completes so the provider removes its
managed copy. A direct Secret deletion would be reconciled.

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
PVC. Other instances, databases, and the shared namespace remain.
Deletion follows the host StorageClass retention policy. Back up control-plane
and database volumes before removing an instance or Datalab.
