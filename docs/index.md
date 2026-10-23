# Provider Datalab

Provider Datalab creates shared data workspaces on Kubernetes. A team declares
its users, sessions, and services in a `Datalab` resource. Crossplane creates
the resources from the platform's shared settings.

The platform operator installs the controllers and sets the identity,
network, storage, security, quota, and backup rules. Users can then work with
data through the browser or start a session with an editor and terminal.

## Create a workspace

After [installation](how-to-guides/installation.md), apply a resource such as:

```yaml
apiVersion: pkg.internal/v1beta2
kind: Datalab
metadata:
  name: demo
  namespace: workspace
spec:
  users:
  - alice
  sessions:
  - name: default
```

This creates a workspace for Alice with a persistent home directory. Educates
runs its editor, terminal, and tools. Stopping the session keeps its workspace
PVC; starting it again uses the same volume.

The shared Data service, packageR, gives Alice a file browser for the Datalab's
object storage. When a permanent Data address is enabled, she can use it
without a running session. To publish files, place them in the Datalab's
`public` folder and send the public share link. Readers do not need an account.
See [Data and sharing](how-to-guides/usage_concepts.md#data-and-sharing).

## Add managed services

The same resource can request services for the team:

| Field | Service |
| --- | --- |
| `spec.databases` | PostgreSQL clusters and logical databases |
| `spec.documentStores` | MongoDB stores |
| `spec.cacheStores` | Redis stores |
| `spec.vectorStores` | Qdrant stores |
| `spec.registry` | A Docker registry |

The cluster needs the operator for each requested managed store. The platform
team manages its storage, backups, upgrades, and deletion. Provider Datalab
uses an existing object-storage endpoint and credentials; it does not create
buckets. [Provider Storage](https://provider-storage.versioneer.at/) can
create those separately.

## Read the guides

Start with [Installation](how-to-guides/installation.md) to prepare the
platform. [Use a Datalab](how-to-guides/usage_concepts.md) explains the resource
fields with examples for sessions, stores, Data, and workshop content.

[Authentication](how-to-guides/authentication.md) covers browser sign-in and
Datalab roles. [Security](security/index.md) explains the other access
controls. For command-line data access, use [S3 client access](how-to-guides/s3-access.md).
For services you deploy yourself, use [Additional services](how-to-guides/additional_services.md).

The [API reference](reference-guides/api.md) lists every field.
[ADR-001](architecture/0001-use-the-datalab-crd-as-the-workspace-contract.md)
explains the choice of the Datalab API and Educates runtime.
