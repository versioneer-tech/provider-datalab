# Tests

Use the [development setup and check commands](../README.md#development).
The unit suite checks helpers and rendered resources with disposable function
containers and Keycloak. The [integration guide](integration/README.md) covers
deployed service checks and target requirements.

## Select checks

Follow [check selection](../README.md#checks). File and docs checks use
`tests/checks.bash` locally and in CI. Python security-policy tests are part of
the unit suite.

## Unit suite

The full suite renders every base example, compares the output with `dyff`,
and checks behavior against a shared set of function containers. Two workers
run the behavior suites and report their durations. The real Keycloak tests
check login, offline refresh, and token exchange.

For focused commands, see [Checks](../README.md#checks). Examples `001`, `002`,
and `003` also select the Data exposure, backup/store, and environment checks.
A focused run does not replace full runtime validation.

## Test files

| Files | Checks |
| --- | --- |
| `test_security.py` | Release selection, candidate checks, scan failures, image digest vulnerability exceptions, expiry, and tool integrity. |
| `ci-checks.py` | Required check selection, including unknown and untracked files. |
| `test_build.py`, `test_composition_helpers.py` | Build input, TTL values and stable service credentials. |
| `test_credentials.py`, `test_cleanup.py`, `test_snapshots.py` | Login and token handling, Pod cleanup, snapshot retention and access. |
| `test_postgres.py`, `test_valkey.py` | PostgreSQL credentials and Valkey snapshot retention, consistency, failure handling, and replacement. |
| `test_harness.py`, `test_probes.py` | Cluster selection, capability probes, workload health checks, and protection of unrelated resources. |
| `vclusters.py`, `admission/`, `volumes.py` | Virtual cluster access and lifecycle, host volumes, bindings, and admission rules. |
| `token-exchange.py`, `keycloak_policy.py` | Role restrictions and real Keycloak login, refresh, and exchange. |
| `oauth2.py`, `s3-connections.py`, `service-connections.py` | Discovery and credentials when sources change, disappear, or return. |
| `exposure.py`, `settings.py`, `stores.py`, `registry.py`, `backups.py` | Service settings, routes, images, credentials, and backups. |
| `environment-schema.py`, `environment-selection.py`, `response-ttl.py` | Input validation, environment merging, function TTLs, and readiness. |

Use representative inputs. Snapshots check rendered resource specs. Use
separate assertions for behavior such as credential rotation, data retention,
or denied access. Avoid repeating snapshot fields or fixing a test to an
internal hash, message, or call order unless the behavior requires it.

The disposable unit-test Keycloak server has ten minutes to build and import its test realm.
It checks issued tokens for login, offline refresh, and restricted exchange.
A separate login client omits workspace roles despite group membership.
With Full Scope Allowed off, explicit role scope mappings restore `ws_access`
and `ws_api` in a fresh token. Unassigned administrator roles, profile roles,
and roles from another workspace stay absent.

The TLS integration fixture allows ten minutes for startup and fifteen minutes
for deployment rollout. Its first start builds configuration and creates the
database schema.

## Fixtures

Inputs are in [`examples/base/`](../examples/base).
[`environmentconfig.yaml`](environmentconfig.yaml) supplies `datalab` and
`datalab-custom`. Storage fixtures use different endpoints to check that Secret
values take precedence over environment settings.

| Example | Environment | Main checks |
| --- | --- | --- |
| `001` | `datalab` | Data and credential rotation |
| `002` | `datalab` | Writable Data and managed stores |
| `003` | `datalab-custom` | Virtual clusters, bound volume, read-only Data, PostgreSQL |
| `004` | `datalab-custom` | Custom service settings |

Renders go to `/tmp`; snapshots are in `tests/expected/`. Normalize a render
with `python3 tests/render.py /tmp/rendered.yaml`. Review its differences before
replacing a snapshot. Reuse an example when it covers the behavior under test.

## STAC example image

Build the image for the [STAC example](../examples/vcluster/stac-fastapi.yaml)
from the repository root. Push it to a registry that the host nodes can read:

```bash
docker build -f tests/vcluster/catalog.Dockerfile -t registry.acme.com/team/catalog:demo .
docker push registry.acme.com/team/catalog:demo
```

Use that reference for `__CATALOG_IMAGE__` in the example. Follow the
[catalog guide](../docs/how-to-guides/vcluster.md#datalab-stac-catalog) to run it.
