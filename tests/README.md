# Tests

The unit suite checks rendered resources and helper behavior. It needs Docker
for the composition functions and a disposable Keycloak server. The
[integration suite](integration/README.md) checks deployed services in a test cluster.

## Select checks

Use the same check selection as [GitHub Actions](../.github/workflows/pr.yaml):

```bash
python3 scripts/ci-checks.py --base origin/main
```

Use the pull request base or target branch. Without `--head`, the comparison
includes committed, staged, unstaged, and untracked changes.

- `docs_only=true`: run the documentation checks below.
- `docs_only=false`: also run the full unit suite and all integration profiles.

Only Markdown, documentation images under `docs/imgs/`, and `mkdocs.yml`
changes qualify as documentation only. Dependency files and unknown files
select the full suite, including files under `docs/`.
An empty or unavailable comparison selects all checks. Draft pull requests run
units but defer cluster tests until the pull request is ready for review.

## Documentation checks

Install the locked requirements as described in the root
[README](../README.md#development), then run:

```bash
python3 tests/ci-checks.py
python3 -m unittest discover -s tests -p test_security.py -v
python3 scripts/install-tools.py actionlint gitleaks
build/tools/actionlint -shellcheck=
python3 scripts/security.py files --reports build/file-security
mkdocs build --strict --site-dir /tmp/provider-datalab-docs
pre-commit run --all-files
git diff --check
```

Check changed commands and links. Documentation-only changes need no Docker
or Kubernetes cluster.

## Unit suite

Install Docker, the Crossplane CLI, `dyff`, OpenSSL, Python, Go, and `pre-commit`.
Start Docker. Follow the [build instructions](../templates/README.md) to install
Python dependencies and generate `composition.yaml`.

```bash
bash tests/unit.bash
pre-commit run --all-files
git diff --check
```

For a quick check without Docker, run `bash tests/unit.bash fast`. This checks
the generated composition and discovers `test_*.py` with Python's `unittest`.
To run one of these files:

```bash
python3 -m unittest discover -s tests -p test_credentials.py -v
```

`bash tests/unit.bash 001` selects one example render. Shared behavior checks
still run. The full suite uses two workers for behavior suites after the shared
function containers start. It keeps each suite's output together and reports
its duration. YAML parsing uses LibYAML when available; no checks are skipped. Examples `001`, `002`, and `003` also select the Data exposure,
backup/store, and environment-setting checks.

## Test files

| Files | Checks |
| --- | --- |
| `test_build.py`, `test_composition_helpers.py` | Build input, TTL values and stable service credentials. |
| `test_credentials.py`, `test_cleanup.py`, `test_snapshots.py` | Login and token handling, Pod cleanup, snapshot retention and access. |
| `test_postgres.py`, `test_valkey.py` | Store snapshot retention, consistency, failure handling, replacement, and PostgreSQL credentials. |
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

The disposable unit-test Keycloak server has five minutes to import its test realm.
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
