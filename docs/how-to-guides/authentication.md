# Authentication

Provider Datalab creates Keycloak clients, roles, groups, and memberships for
each Datalab. Users in `spec.users` must already exist in the configured realm.
The main confidential client has the Datalab name.

| Client role | Assigned to | Purpose |
| --- | --- | --- |
| `ws_access` | Datalab users | Data access |
| `ws_admin` | Datalab administrators | Data access with the administrator role |
| `ws_api` | Main client service account | Machine access to supported data endpoints |
| `vcluster:vc0:namespace-demo` | Namespace profile client | Kubernetes permissions in `demo` |
| `vcluster:vc0:cluster-admin` | Administrator profile client | Virtual cluster administration |

The virtual cluster rows show example profiles in instance `vc0`. Each
role uses `vcluster:<instance>:<group>` to keep instance permissions separate.

## Data endpoints

Published Data uses an OAuth proxy with the generated Datalab client.
Browser access requires Datalab membership. The optional S3 endpoint checks
the Datalab audience and one of `ws_access`, `ws_admin`, or `ws_api`.

Set `iam.issuerURL` and `iam.internalURL` in the EnvironmentConfig. Extra
audiences can be supplied in `iam.extraAudiences`. Other token issuers or
OAuth clients must emit the expected audience and client roles.

The internal package-r port trusts the approved caller's identity header.
Restrict access to that port. Public shares permit access without sign-in;
place only intended public content in the shared folder.

The service namespace contains `<datalab>-oauth2-client` with the proxy's
client and cookie credentials. Restrict access and rotate credentials when
access changes. [Connection sets](connections.md) describe client outputs.

## Vcluster profiles

Each profile has its own confidential OAuth client and service account. Its
token contains the configured vcluster role and the Datalab audience. The
virtual API verifies issuer, signature, expiry, audience, and role. Workspace
roles alone do not grant Kubernetes access.

Kubernetes RBAC enforces namespace boundaries. Changing a kubeconfig's default
namespace does not grant permissions elsewhere. Removing a group revokes its
role, client, RBAC binding, and connection Secret. Existing valid tokens lose
that group's access after reconciliation.

Downloaded profile files use a shared service identity and contain a client
credential. Anyone who holds a file can act as that profile. See
[vcluster access](vcluster.md) for download and use.
