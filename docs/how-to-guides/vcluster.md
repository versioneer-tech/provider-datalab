# Use a Datalab virtual cluster

Declare each virtual Kubernetes cluster under `spec.vclusters`:

```yaml
apiVersion: versioneer.at/v1
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

Each entry creates one control plane in the Datalab-named service namespace. Add
`vc1` alongside `vc0` to create another cluster. An empty map creates none.

Use one Datalab per team and add virtual clusters as needed. Configure
explicit service Secret bindings for application namespaces. See
[connection bindings](connections.md#bind-a-connection).

Each virtual cluster installs Agent Sandbox CRDs and its controller. See
[Sandboxes](sandboxes.md) to start sandboxd, use its APIs, and keep workspace
files on a session PVC.

## API access

The virtual API for `vc0` is:

```text
https://s-joe.lab.acme.com/.vc0
```

The Gateway removes `/.vc0` and forwards to that instance with backend TLS
validation. Workload Ingress and Gateway synchronization is disabled; use
Kubernetes port forwarding to reach a workload Service.

### Roles and profiles

The API validates issuer, Datalab audience, signature, expiry, and configured
roles under `resource_access.<datalab>.roles`. Kubernetes RBAC controls which
operations those roles permit.

| Caller | Virtual API access |
| --- | --- |
| A user in `spec.users` | Explicit additional profiles, through the Datalab users group |
| A Datalab administrator | Additional profiles and each instance's built-in `vcluster_<instance>_cluster-admin` role |
| The Datalab service account | None by default; its only default role is `ws_api` |
| An identity with an assigned `vcluster_<instance>_<group>` role | The group's configured namespace and Kubernetes role |

`groups` defines additional profiles with `view`, `edit`, or `admin` access.
The provider grants their client roles to both Datalab groups. Optional
OAuth scopes select which assigned roles appear in Datalab client tokens.
Roles are specific to an instance. See [token exchange](authentication.md#user-token-exchange)
for a token limited to one selected profile.

A downloaded profile selects the endpoint and default namespace. It neither
grants access nor reduces permissions already present in the caller's token.
The `cluster-admin` profile cannot elevate a namespace caller, and a namespace
profile cannot restrict a caller who already has the admin role.

Provider Datalab already assigns workspace administrators `ws_admin` and
each instance's `vcluster_<instance>_cluster-admin` role through the managed
administrators group. No additional manual role assignment is needed.
The API checks the instance role in the token. An unrelated manual assignment
of `ws_admin` alone does not grant virtual API access.

### Download a profile

Resolve its Secret reference from `status.connections`; do not construct the
name. Each profile Secret contains `kubeconfig`, the Datalab client's public
`client-id`, and `issuer-url`. Public CA certificates can be included. It
contains no client secret, token, private key, or client certificate. The
provider keeps the recovery kubeconfig private.

`ready: true` reports runtime, routing, role, scope, and RBAC readiness. It does
not imply caller authorization or require caller credentials to be present.
The kubeconfig includes a Python 3 credential helper.
Additional profiles select `--token-only` and read an access token file
supplied by the caller. They require no OAuth client ID or client secret and
make no token requests. The built-in `cluster-admin` profile retains the
Datalab client ID and issuer. It accepts a caller token or a separate client
secret for device login as a user. It never requests a service-account token.
No separate helper file is needed on the caller's machine.

The following cases use Datalab `s-joe`, instance `vc0`, and the additional
`namespace-demo` profile from the example above. Use Bash with `kubectl`,
`jq`, `base64`, and Python 3 installed. Set the host context used to read
Datalab metadata and download Secrets:

```bash
set -euo pipefail
umask 077
host_context=your-host-context
```

Replace `your-host-context` with the platform context. Download commands use
that context explicitly. Commands with `--kubeconfig` connect to the virtual
cluster. If you cannot read the host Datalab or its Secrets, obtain the files
from the platform operator and continue with the local steps.

| Case | Local kubeconfig file | Credential supplied by the caller |
| --- | --- | --- |
| Human device login | `s-joe-vc0.kubeconfig` | Datalab OAuth client secret; browser login identifies the user |
| Delegated access | `s-joe-vcluster-vc0_namespace-demo.kubeconfig` | An exchanged user access token for the selected profile |

These are local filenames. Always resolve the host Secret names and namespaces
from Datalab status. The download commands require a ready profile.

### Human access

This case logs in as your Keycloak user. The client secret authenticates
the Datalab client; your user identity and assigned roles control API access.

#### 1. Download the profile with device login

Select the built-in `cluster-admin` profile. Its helper supports device login
even when your user has only an additional namespace role.

```bash
read -r profile_namespace profile_secret < <(
  kubectl --context "${host_context}" -n workspace get datalab s-joe -o json | \
    jq -er '.status.connections[] |
      select(.type == "vcluster" and .instance == "vc0" and
             .group == "cluster-admin" and .ready == true) |
      .secretRef | [.namespace, .name] | @tsv'
)
kubectl --context "${host_context}" -n "${profile_namespace}" \
  get secret "${profile_secret}" -o jsonpath='{.data.kubeconfig}' | \
  base64 --decode > s-joe-vc0.kubeconfig
```

#### 2. Download the OAuth client secret

Resolve the ready client credential reference from `status.oauth2`. Save
only its decoded client secret value in a private file. The helper does not
read a Secret YAML document.

```bash
unset DATALAB_ACCESS_TOKEN_FILE
mkdir -p "$HOME/.config/datalab"
chmod 700 "$HOME/.config/datalab"
export DATALAB_CLIENT_SECRET_FILE="$HOME/.config/datalab/s-joe-client-secret"
read -r oauth_namespace oauth_secret < <(
  kubectl --context "${host_context}" -n workspace get datalab s-joe -o json | \
    jq -er '.status.oauth2[] |
      select(.type == "client" and .ready == true) |
      .secretRef | [.namespace, .name] | @tsv'
)
kubectl --context "${host_context}" -n "${oauth_namespace}" \
  get secret "${oauth_secret}" -o json | \
  jq -er '.data.clientSecret // .data.client_secret' | \
  base64 --decode > "$DATALAB_CLIENT_SECRET_FILE"
chmod 600 "$DATALAB_CLIENT_SECRET_FILE"
```

You can instead obtain that value through the platform's credential process.
If `DATALAB_CLIENT_SECRET_FILE` is unset, the helper asks for the secret in an
interactive terminal without showing or saving the input. A valid cached
access token needs no secret. Refresh and new login need the secret again.

#### 3. Start kubectl and approve the device login

For a user with `vcluster_vc0_cluster-admin`, run:

```bash
kubectl --kubeconfig ./s-joe-vc0.kubeconfig get namespaces
kubectl --kubeconfig ./s-joe-vc0.kubeconfig auth can-i '*' '*' --all-namespaces
```

On the first command, the helper prints a verification URL and a user code.
Open the URL in a browser, enter the code, and sign in as your Keycloak user.
The browser can run on another device. After approval, kubectl continues.
The authorization check returns `yes` for a user whose token contains the
built-in administrator role and whose binding is ready.

The default login requests `openid offline_access s-joe:interactive`. The
interactive scope permits
`ws_access`, `ws_admin`, and built-in vCluster administrator roles that your
user holds. It does not request all additional namespace profiles.

#### 4. Select scopes for other assigned user roles

For a user assigned `vcluster_vc0_namespace-demo`, add its OAuth scope to a
local copy of the device-login profile:

```bash
kubectl --kubeconfig ./s-joe-vc0.kubeconfig config view --raw -o json | \
  jq '.users[].user.exec.args += [
    "--scope", "s-joe:interactive",
    "--scope", "s-joe:vclusters_vc0_namespace-demo"
  ]' > s-joe-vc0-human.kubeconfig
kubectl --kubeconfig ./s-joe-vc0-human.kubeconfig -n demo get pods
kubectl --kubeconfig ./s-joe-vc0-human.kubeconfig -n demo auth can-i create deployments
```

JSON is also a valid kubeconfig format. This copy keeps the embedded helper,
endpoint, and CA settings. Add another `--scope` pair for each additional
profile you need. Each scope includes only roles that your user holds.
A user with only the example namespace role gets `edit` access in `demo`,
not cluster administration. A user who also holds the built-in administrator
role retains that wider access when requesting `s-joe:interactive`.

#### 5. Reuse the login

The helper saves the access token, offline refresh token, and the local
login deadline in:

```text
~/.cache/datalab/oidc/<hash>.json
```

It uses `$XDG_CACHE_HOME/datalab/oidc` when `XDG_CACHE_HOME` is set. Set
`DATALAB_TOKEN_CACHE_DIR` to select another private directory. The directory
has mode `0700`; token files have mode `0600`. The hash separates issuer,
client ID, and scopes. Different scopes can require a separate device login.
The helper does not store the client secret in this cache.

Later kubectl commands reuse a valid token without a browser prompt. Near
expiry, the helper requests a new token with the cached offline refresh token
and the client secret. It saves the updated token response, including any
replacement refresh token. Refresh keeps the user's current assigned
permissions within the login's requested scopes. If Keycloak rejects the
refresh token with
`invalid_grant`, it starts device login again. There is no background refresh
while kubectl is idle. In a new shell, set `DATALAB_CLIENT_SECRET_FILE` again
if refresh or login is needed.

To sign in as another user, run the standalone helper from this repository:

```bash
python3 scripts/vcluster-credentials.py \
  --issuer https://identity.acme.com/realms/acme --client-id s-joe \
  --force-login >/dev/null
```

Use the same issuer, client ID, scopes, cache directory, and secret source as
the downloaded profile. Add the same `--scope` pairs for the modified profile.
For a private issuer CA, add `--issuer-ca /path/to/issuer-ca.pem`. Generated
device-login profiles already contain the configured issuer CA.

#### Human login lifetime

CLI device login requests offline access by default. Access tokens stay
short-lived; the CLI obtains replacements without another device prompt while
the offline session remains valid. Refresh does not extend the local login
deadline.

| Limit | Default or setting | Effect on kubectl |
| --- | --- | --- |
| Access token | Realm or client Access Token Lifespan; upstream default is 5 minutes | The helper refreshes it when needed. |
| CLI cached login | 30 days after device approval | The helper starts device login again after this deadline. |
| Client offline idle timeout | Provider sets 30 days | The session can expire if no refresh occurs within this period. |
| Client offline maximum | Provider sets 30 days | Keycloak applies this limit when the realm enables Offline Session Max Limited. |
| Realm offline limits and revocation | Platform settings | Shorter realm limits or revoked offline access can end the login sooner. |

The realm must permit `offline_access`, and the user must have the standard
realm `offline_access` role. Provider Datalab adds the built-in offline scope
to the client's optional scopes. Keycloak normally grants its role through
the realm's default roles. Ordinary SSO Session Idle/Max limits do not govern
an offline session. Check **Realm settings > Sessions** and
**Clients > s-joe > Advanced** for the deployed offline limits. The device
code has a separate approval timeout.

An existing cache from a login without `offline_access` is not reused for the
new scope set. Download a current kubeconfig and approve device login once.
The new cache then supports automatic refresh for the CLI login period.
See [Keycloak offline access](https://www.keycloak.org/docs/latest/server_admin/index.html#_offline-access)
and [login lifetime](authentication.md#login-lifetime).

> [!NOTE]
> On Keycloak versions older than 26.8.1, device login token refresh is unreliable; use `--force-login` to start a new device login when refresh fails.

### Delegated access

This case uses an access token issued for a human user and passed to another
caller. The recipient needs the selected kubeconfig and token, with no client
secret or browser login.

#### 1. Obtain a token for the selected profile

The user or platform service performs
[token exchange](authentication.md#user-token-exchange) with the user's access
token as `subject_token`. For the example profile, request:

```text
scope=s-joe:vclusters_vc0_namespace-demo
audience=s-joe
requested_token_type=urn:ietf:params:oauth:token-type:access_token
```

The OAuth scope is `s-joe:vclusters_vc0_namespace-demo`; the corresponding
Keycloak client role is `vcluster_vc0_namespace-demo`. Exchange can select
only a role the user holds. Before passing on the result, the issuing service
must check that `resource_access.s-joe.roles` contains that role and omits
administrator and unrelated profile roles. `ws_api` can also be present.
The token keeps the human user's subject. Selecting a kubeconfig alone does
not restrict a token with wider permissions.

Give the recipient the returned JWT access token through a private file.
Keep the client secret, original user token, and refresh token with the user
or service that performs exchange. An ID token cannot replace this access
token.

#### 2. Download the selected profile

Using the host context from the download setup, select `namespace-demo`:

```bash
read -r profile_namespace profile_secret < <(
  kubectl --context "${host_context}" -n workspace get datalab s-joe -o json | \
    jq -er '.status.connections[] |
      select(.type == "vcluster" and .instance == "vc0" and
             .group == "namespace-demo" and .ready == true) |
      .secretRef | [.namespace, .name] | @tsv'
)
kubectl --context "${host_context}" -n "${profile_namespace}" \
  get secret "${profile_secret}" -o jsonpath='{.data.kubeconfig}' | \
  base64 --decode > s-joe-vcluster-vc0_namespace-demo.kubeconfig
```

The platform operator can supply this file if the recipient has no host
access. The profile uses `--token-only`: it cannot start device login or make
refresh requests.

#### 3. Set the token file and run kubectl

Save the received access token as
`~/.config/datalab/s-joe-vc0-namespace-demo.token`. The file must contain only
the JWT, without a JSON wrapper or `Bearer ` prefix. Then run:

```bash
unset DATALAB_CLIENT_SECRET_FILE
export DATALAB_ACCESS_TOKEN_FILE="$HOME/.config/datalab/s-joe-vc0-namespace-demo.token"
chmod 600 "$DATALAB_ACCESS_TOKEN_FILE"
kubectl --kubeconfig ./s-joe-vcluster-vc0_namespace-demo.kubeconfig -n demo get pods
kubectl --kubeconfig ./s-joe-vcluster-vc0_namespace-demo.kubeconfig -n demo \
  auth can-i create deployments
kubectl --kubeconfig ./s-joe-vcluster-vc0_namespace-demo.kubeconfig \
  auth can-i create namespaces
```

The example `edit` profile permits Deployment creation in `demo`; namespace
creation is denied. `DATALAB_ACCESS_TOKEN_FILE` contains a file path, not the
token value. The helper reads that file and returns the token to kubectl.
It makes no login or refresh request and does not use the device-login cache.

#### Delegated token lifetime and revocation

The received token's `exp` claim is its expiry time. The exchange response's
`expires_in` reports its remaining lifetime when issued. Do not assume a
fixed duration or that exchange starts a new full session. The helper sets
`ExecCredential.expirationTimestamp` from `exp`. When the token expires, ask
the issuing user or service for a new exchange result and replace the token
file. The recipient has no refresh token to renew it.

To display the expiry in UTC without printing the token, run:

```bash
python3 - "$DATALAB_ACCESS_TOKEN_FILE" <<'PY'
import base64
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

payload = Path(sys.argv[1]).read_text().strip().split('.')[1]
claims = json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))
print(datetime.fromtimestamp(claims['exp'], timezone.utc).isoformat())
PY
```

This command reads the expiry claim; the virtual API verifies the signature
and decides whether to accept the token.

The virtual API validates JWTs locally. It does not ask Keycloak whether each
token has been revoked. Removing a user's Keycloak role, ending the login
session, rotating the client secret, or deleting a local token file does not
reliably invalidate copies of an already issued JWT at this API. Keycloak
also documents that revoking the original access token does not revoke an
exchanged access token. See [token exchange revocation](https://www.keycloak.org/securing-apps/token-exchange#_revocation).

Without an API authorization change, expect an issued token to remain usable
until `exp`. To deny access sooner, the platform operator can remove the
affected configured profile or its Kubernetes RBAC binding. This removes
access for all callers that depend on that role or binding, not just one
token. Apply changes through the source configuration and allow for
reconciliation. This setup has no individual JWT revocation list. The same
limit applies to access tokens cached after human device login. Revoke its
offline session in Keycloak to stop further CLI refresh. Ordinary browser
logout does not revoke offline access. Neither action erases issued JWTs.

| Action | Human device login | Delegated access token |
| --- | --- | --- |
| Access token expires | Helper attempts refresh with the client secret. | Recipient must obtain a new token. |
| Offline session expires or is revoked | Refresh stops; a new device login is needed. | An issued token can remain usable until `exp`. |
| Keycloak role assignment is removed | New tokens lose the role; issued tokens can retain it. | An issued token can retain the role until `exp`. |
| Configured profile or required RBAC binding is removed | Access is denied after the API configuration or binding changes. | The same denial applies to the delegated token. |

### Machine access

An identity administrator must explicitly assign the required vcluster role
to the existing Datalab service account. For example,
`vcluster_vc0_namespace-demo` permits the configured operations in `demo`.
Do not add this account to a human group. Request the profile's optional scope
when using a separately assigned role; the default machine token has only
`ws_api`. Obtain the token before using the downloaded profile.

Obtain the Datalab client secret from the source in `status.oauth2` through
an authorized Secret-delivery process. This is the `<datalab>-oauth-client`
Secret. Use it to authenticate a token request with these parameters:

```text
grant_type=client_credentials
client_id=s-joe
scope=s-joe:vclusters_vc0_namespace-demo
```

Save the returned access token in a private file and use
`DATALAB_ACCESS_TOKEN_FILE` as shown above. The downloaded helper accepts only
an access token file for additional profiles. The built-in `cluster-admin`
helper uses a supplied client secret for user device login, not machine access.
Client credentials alone produce a token with only `ws_api` and cannot access
the virtual API. An explicitly granted machine role still requires its
matching optional scope in a separate token request.
A profile download supplies no credentials or role grants.

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

The provider publishes each service connection in `status.connections`, with its `type`,
`name`, `secretRef`, and readiness. A binding selects the same `type`
and `name` pair. The mapping uses that connection's `secretRef`.

The connection sources are:

| Type | Name | Published host Secret |
| --- | --- | --- |
| `s3` | `primary` | The Secret with the same name as the Datalab |
| `postgres` | A key in `spec.databases` | A connection copy in the Datalab namespace |
| `mongo` | A key in `spec.documentStores` | A connection copy in the Datalab namespace |
| `redis` | A key in `spec.cacheStores` | A connection copy in the Datalab namespace |
| `registry` | `primary` | A connection copy in the Datalab namespace |
| `custom` | A predefined Secret name | A connection copy in the Datalab namespace |

Only declared service instances can be selected. The storage source namespace
comes from `EnvironmentConfig.data.storage.secretNamespace`, or the claim
namespace when unset. Use a custom connection for credentials such as a
GitHub token.

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
is listed in `status.connections` after its source is confirmed ready. Its
`ready` value stays false until the published copy is available and current.
Missing custom sources do not block Datalab readiness.

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

vCluster creates the target namespace and syncs the whole Secret, including
source updates and deletion. Secret keys keep their source names. Only ready,
unambiguous connections generate mappings. Missing or unready references are
skipped; reconciliation adds or removes mappings as source readiness changes.
Source readiness does not confirm delivery inside the virtual cluster.

## Platform settings

Merge these values into the Datalab's EnvironmentConfig:

```yaml
data:
  iam:
    issuerURL: https://identity.acme.com/realms/acme
  ingress:
    domain: lab.acme.com
  httpRoute:
    enabled: true
    parentName: default
    parentNamespace: contour
    sectionName: workspaces-https
    httpSectionName: workspaces-http
  vcluster:
    storage: 5Gi
    storageClasses:
      allowed: [sbs-default]
      default: sbs-default
```

For a private issuer CA, set `vcluster.issuerCA`. An optional HTTPS
`vcluster.discoveryURL` can provide separate discovery routing with the same
issuer. For a private Gateway CA, set `ingress.certificateAuthority`.

### Host requirements

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

### Storage and control-plane resources

The `vcluster` EnvironmentConfig section supplies defaults for all declared
instances. `spec.vclusters.<name>.storage` overrides the control-plane PVC size.
`vcluster.storageClassName` selects its class; otherwise the default class is
used. Only classes in `vcluster.storageClasses.allowed` are exposed to virtual
workloads. A host admission policy enforces this list for each syncer.
Control-plane, workload, database, and session PVCs share the
`defaults.overallQuota.storage` limit. All Pod CPU and memory requests and limits
count against the same [host namespace quota](installation.md#resource-quotas-and-container-defaults),
across every virtual namespace and cluster in the Datalab.

Set `vcluster.resources.requests` and `vcluster.resources.limits` in the
EnvironmentConfig to change control-plane resources. Both the native vCluster
configuration and the host StatefulSet use these values. The defaults are CPU
`200m` and memory `1Gi` for requests, and CPU `4` and memory `4Gi` for limits.
Ephemeral storage defaults to a `1Gi` request and a `10Gi` limit. Each supplied
field overrides its default.

### SQLite settings

To limit SQLite to two open connections and one idle connection, merge:

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
virtual namespace `demo`. The migration Secret uses `host`, `port`, `user`, and
`password`. The API Secret uses the PostgreSQL environment variable names above.
Use an operator-approved [Secret binding](connections.md#bind-a-connection)
with `type: postgres` and `name: pg0` for migration. Supply the API login
separately with suitable backend permissions.
Build the image from `tests/vcluster/catalog.Dockerfile`, push it to your registry, and
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
caller role boundaries, public profiles, persistent volumes, and the catalog.
The catalog test creates a collection and item, searches it, restarts the API,
and repeats the search after a control-plane restart.

## Removal

Removing a group removes its role and binding after reconciliation while
retaining its virtual namespace data. Removing an instance removes its runtime
and control-plane PVC. Other instances, databases, the registry, and the shared
namespace remain. Deletion follows the host StorageClass retention policy.
Back up control-plane and database volumes before removing an instance or Datalab.

Removing a Keycloak role assignment or client prevents new tokens with those
grants. Already-issued JWTs can remain valid until expiry because the API
validates them locally. To deny access sooner, remove the affected configured
role or Kubernetes binding. Allow for reconciliation before checking revocation.
