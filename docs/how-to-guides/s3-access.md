# S3 client access

The read-only S3 endpoint is experimental. Range reads currently return HTTP
`200` with `Content-Range`, rather than HTTP `206`.

## Enable the endpoint

Set `EnvironmentConfig.data.httpRoute.enableS3: true` to add a read-only
S3 endpoint on the shared Data hostname for every Data-enabled Datalab in the
environment. There is no per-Datalab override. Set `httpRoute.enabled: true`
and `ingress.enabled: false`. Use a Gateway API controller that supports
HTTPRoute header regular expressions, such as Contour, with HTTP and
TLS-terminating HTTPS listeners for the Data hostnames. Add a ReferenceGrant
if the Gateway uses a certificate Secret from another namespace.

Merge these settings into the selected EnvironmentConfig:

```yaml
data:
  ingress:
    enabled: false
    domain: lab.acme.com
  httpRoute:
    enabled: true
    enableS3: true
    parentName: default
    parentNamespace: gateway-system
    sectionName: workspaces-https
    httpSectionName: workspaces-http
```

With `enableS3: false` or omitted, the same HTTPRoutes serve only the browser
endpoint. The controller does not create an S3 service or S3 routing rule.

Allow the runtime to reach object storage through the environment's network
settings. The composed S3 policy permits IAM traffic on TCP port 8080 in the
configured IAM namespace. The Gateway must be able to reach the S3 service.
See [Network access](installation.md#network-access) for the shared settings.

## S3 access to s-joe

The [Joe example](https://github.com/versioneer-tech/provider-datalab/blob/main/examples/base/001-lab.yaml)
creates the Datalab `s-joe` and selects `datalab-custom`. With the example
EnvironmentConfig, its endpoint is `https://s-joe.lab.acme.com` and its issuer
is `https://identity.acme.com/realms/acme`. Replace these example DNS names
with your environment's values.

Keycloak checks `CLIENT_SECRET` and issues a JWT. The AWS CLI sends it as
`AWS_SESSION_TOKEN` in the `X-Amz-Security-Token` header. NGINX checks the
tenant ID and passes the token to oauth2-proxy, which checks its signature,
issuer, audience, expiry, and Datalab role. After authorization, `rclone serve
s3` checks the original AWS SigV4 request using `s-joe` as both signing
values. It serves read-only data through separate upstream storage credentials.

```text
AWS CLI
  │ HTTPS :443 → s-joe.lab.acme.com
  ▼
Contour / Envoy
  │ HTTP → Service data-s3 :8080
  ▼
NGINX gateway :8080
  ├─ Auth subrequest → oauth2-proxy 127.0.0.1:4180
  │                     └─ Fetch signing keys → Keycloak
  │                        (example internal URL: keycloak.keycloak:8080)
  │
  └─ If authorized → rclone 127.0.0.1:8081
                         └─ HTTPS → upstream S3 storage (s3.acme :443)
```

NGINX, oauth2-proxy, and rclone share the `data-s3` Pod and use localhost for
calls within that Pod. The Gateway implementation and upstream storage depend
on your environment. The example internal Keycloak URL uses Service port
`8080`; other installations can use a different Service port.

| Credential field | Value |
| --- | --- |
| `AccessKeyId` | `s-joe` |
| `SecretAccessKey` | `s-joe` |
| `SessionToken` | Keycloak JWT access token |
| `Expiration` | Token expiry |

The signing values are public tenant identifiers. They do not grant access
without a valid JWT. The token must include `s-joe` in `aud` and at least one
of `ws_access`, `ws_admin`, or `ws_api` under `resource_access.s-joe.roles`.
These are Keycloak client roles, separate from OAuth scopes. All three permit
reads. The upstream storage policy limits which buckets and objects the
Datalab can read. Missing or invalid tokens cannot use a browser cookie or an
unsigned request as a fallback.

The generated Datalab client adds its own audience when S3 is enabled. Other
OAuth clients must emit the same audience and tenant roles. Service-account
tokens do not need a verified email address.

The following Bash commands use the
[credential helper](https://github.com/versioneer-tech/provider-datalab/blob/main/tests/s3/s3-credentials.py)
from the repository root. It uses the client credentials grant with `s-joe`
as the client ID. At the prompt, enter the `client_secret` from the generated
`s-joe-oauth2-client` Secret in the runtime namespace. Replace `example-data`
with a bucket that the Datalab can read. Both methods use path-style requests.

### Manual token retrieval

```bash
if [ -z "${CLIENT_SECRET:-}" ]; then
  CLIENT_SECRET="$(python3 -c 'import getpass; print(getpass.getpass("CLIENT_SECRET: "))')"
fi
export CLIENT_SECRET
export AWS_ACCESS_KEY_ID=s-joe AWS_SECRET_ACCESS_KEY=s-joe
export AWS_ENDPOINT_URL=https://s-joe.lab.acme.com
export AWS_DEFAULT_REGION=us-east-1
export AWS_PROFILE=s-joe
aws configure set s3.addressing_style path --profile s-joe

credentials="$(python3 tests/s3/s3-credentials.py \
  --tenant s-joe \
  --issuer https://identity.acme.com/realms/acme)"
AWS_SESSION_TOKEN="$(printf '%s' "$credentials" | \
  python3 -c 'import json, sys; print(json.load(sys.stdin)["SessionToken"])')"
export AWS_SESSION_TOKEN
unset credentials

aws s3 ls s3://example-data/
```

Run the token retrieval command again after the token expires, or use automatic
renewal below.

### Automatic token renewal with credential_process

Clear the manual AWS settings so that the CLI uses the profile's credential
process. The CLI obtains new credentials when needed, using the helper's
`Expiration` value.

```bash
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
unset AWS_CONFIG_FILE AWS_PROFILE AWS_ENDPOINT_URL
unset AWS_DEFAULT_REGION AWS_REGION

if [ -z "${CLIENT_SECRET:-}" ]; then
  CLIENT_SECRET="$(python3 -c 'import getpass; print(getpass.getpass("CLIENT_SECRET: "))')"
fi
export CLIENT_SECRET
export AWS_PROFILE=s-joe

aws configure set region us-east-1 --profile s-joe
aws configure set endpoint_url https://s-joe.lab.acme.com --profile s-joe
aws configure set s3.addressing_style path --profile s-joe
aws configure set credential_process \
  "python3 \"$PWD/tests/s3/s3-credentials.py\" --tenant s-joe --issuer https://identity.acme.com/realms/acme" \
  --profile s-joe

aws s3 ls s3://example-data/
```

Keep `CLIENT_SECRET` available in the environment of the AWS CLI or SDK
process. If you move the repository, update the helper's absolute path in the
profile.

The endpoint supports list, HEAD, GET, and byte-range GET requests. It remains
read only when `spec.data.readOnlyMount` is false. Writes and presigned S3 URLs
are rejected. packageR download and share links use the browser route.
