# Unit tests

The suite checks generated resources and helper behavior without a Kubernetes
cluster. Docker runs the composition functions and a disposable Keycloak server.

## Select checks

[GitHub Actions](../.github/workflows/pr.yaml) defines the required checks.
Use the same selection locally, against the target branch or pull request base:

```bash
python3 scripts/ci-checks.py --base origin/legacy
```

Without `--head`, the comparison includes committed, staged, unstaged, and
untracked changes. CI uses `--head` to compare two commits.

- `docs_only=true`: run the documentation checks below. Only Markdown, `docs/`,
  and `mkdocs.yml` changes qualify.
- `docs_only=false`: also run the full unit suite and integration profiles.
  Mixed changes, empty or unavailable comparisons, and manual CI runs use this
  selection.

## Documentation changes

Install `docs/requirements.txt` and `pre-commit`, then run:

```bash
python3 tests/ci-checks.py
mkdocs build --strict --site-dir /tmp/provider-datalab-docs
pre-commit run --all-files
git diff --check
```

Check changed commands and links. Documentation-only changes do not need Docker
or cluster tests.

## Run the suite

Install Docker, the Crossplane CLI, `dyff`, OpenSSL, Python, and `pre-commit`.
Start Docker and follow the [build instructions](../templates/README.md) to
install Python dependencies and generate `composition.yaml`.

```bash
bash tests/unit.bash
pre-commit run --all-files
```

`bash tests/unit.bash fast` runs helper and harness checks without Docker.
`bash tests/unit.bash 001` selects one example; the shared behavior checks still
run. Examples `001`, `002`, and `003` also select Data exposure, backup/store,
and environment-setting checks, respectively.

## What the checks cover

Snapshots check resource specs, readiness rules, and connection status. They
omit generated metadata that changes between runs. The other tests check:

| Tests | Behavior |
| --- | --- |
| `vclusters.py` | Instance isolation, permissions, Secret bindings, Sandbox setup, and session storage. |
| `helpers.py` | Credentials, login, token caches, and build and harness errors. |
| `token-exchange.py`, `keycloak_policy.py` | Role restrictions, refresh, and token exchange with a disposable Keycloak server. |
| `oauth2.py`, `s3-connections.py`, `service-connections.py` | Discovery, credential publication, rotation, source loss, and recovery. |
| `exposure.py`, `settings.py`, `stores.py`, `registry.py` | Routes, storage, network rules, quotas, and environment settings. |
| `backups.py` | Backup enablement, export failures, and invalid Redis snapshots. |
| `response-ttl.py` | TTL defaults, overrides, invalid values, and readiness checks. |
| `environment-schema.py`, `environment-selection.py` | Valid environment names, selection labels, merge order, and duplicate matches. |

The [integration suite](integration/README.md) checks deployed services,
authorization, routing, and persistence in Kind.

## Fixtures

Datalab inputs are in [`examples/base/`](../examples/base).
[`environmentconfig.yaml`](environmentconfig.yaml) supplies `datalab` and
`datalab-custom`. Storage fixtures use different endpoints from the environment
to check that Secret values take precedence.

| Example | Environment | Main checks |
| --- | --- | --- |
| `001` | `datalab` | Data, default environment, credential rotation |
| `002` | `datalab` | Writable Data and managed stores |
| `003` | `datalab-custom` | Virtual clusters, session PVCs, Sandbox setup, read-only Data, PostgreSQL |
| `004` | `datalab-custom` | Services with custom settings |

Renders are written to `/tmp`; expected snapshots are in `tests/expected/`.
Normalize a new render with `python3 tests/render.py /tmp/rendered.yaml` and
review the differences before replacing a snapshot. Use an existing example
when it covers the behavior under test. Add one only for a missing case.
