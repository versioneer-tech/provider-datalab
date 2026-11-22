# Unit tests

The suite checks generated resources and helper behavior without a Kubernetes
cluster. Docker runs the composition functions and a disposable Keycloak server.

## Select checks

[GitHub Actions](../.github/workflows/pr.yaml) defines the required checks.
Use the same selection locally, against the target branch or pull request base:

```bash
python3 scripts/ci-checks.py --base origin/main
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

Install Docker, the Crossplane CLI, `dyff`, OpenSSL, Python, Go, and `pre-commit`.
Go runs the admission policy checks. Start Docker and follow the
[build instructions](../templates/README.md) to install Python dependencies and
generate `composition.yaml`.

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
| `vclusters.py`, `admission/` | Virtual cluster isolation, placement, hibernation and resume, permissions, volume and Secret bindings, and virtual resources. |
| `volumes.py` | Host PVCs without virtual clusters, automatic backups, restore sources, operator retention, and current snapshot counts. |
| `helpers.py` | Credentials, token caches, host Pod cleanup, volume snapshot retention and failure cleanup, snapshot capability and permission checks, build failures, and integration runner errors. |
| `token-exchange.py`, `keycloak_policy.py` | Role restrictions, refresh, and token exchange with a disposable Keycloak server. |
| `oauth2.py`, `s3-connections.py`, `service-connections.py` | Service discovery and credential publication when Secrets change, disappear, or return. |
| `exposure.py`, `settings.py`, `stores.py`, `registry.py` | Routes, service images and database versions, storage, network rules, quotas, and environment settings. |
| `backups.py` | Backup enablement, export failures, and invalid Redis snapshots. |
| `response-ttl.py` | TTL defaults, overrides, invalid values, and readiness checks. |
| `environment-schema.py`, `environment-selection.py` | Valid environment names, selection labels, merge order, and duplicate matches. |

The [integration suite](integration/README.md) checks deployed services,
authorization, routing, and persistence in an existing test cluster or Kind.
Its volume checks recover file contents from CSI snapshots, check retention
and failure handling, and verify storage removal. Dedicated Kind setup supplies
NetworkPolicy enforcement, NFS CSI storage, and snapshot infrastructure.
Existing targets are probed before traffic and snapshot tests. Missing capability
produces a prominent `SKIPPED` message; other tests continue. See the
[integration prerequisites](integration/README.md#select-a-cluster) for the
required APIs, classes, and permissions.
Draft pull requests run documentation and unit checks in CI. Kubernetes
integration steps are deferred until the pull request is ready for review.
Pushes to the configured target branches and manual runs include integration.

## Fixtures

Datalab inputs are in [`examples/base/`](../examples/base).
[`environmentconfig.yaml`](environmentconfig.yaml) supplies `datalab` and
`datalab-custom`. Storage fixtures use different endpoints from the environment
to check that Secret values take precedence.

| Example | Environment | Main checks |
| --- | --- | --- |
| `001` | `datalab` | Data, default environment, credential rotation |
| `002` | `datalab` | Writable Data and managed stores |
| `003` | `datalab-custom` | Virtual clusters, bound host volume, read-only Data, PostgreSQL |
| `004` | `datalab-custom` | Services with custom settings |

Renders are written to `/tmp`; expected snapshots are in `tests/expected/`.
Normalize a new render with `python3 tests/render.py /tmp/rendered.yaml` and
review the differences before replacing a snapshot. Use an existing example
when it covers the behavior under test. Add one only for a missing case.

## STAC example image

Build the image for the [STAC workload example](../examples/vcluster/stac-fastapi.yaml)
from the repository root and push it to a registry that the host nodes can read:

```bash
docker build -f tests/vcluster/catalog.Dockerfile -t registry.acme.com/team/catalog:demo .
docker push registry.acme.com/team/catalog:demo
```

Use that reference for `__CATALOG_IMAGE__` in the example. Follow the
[catalog guide](../docs/how-to-guides/vcluster.md#datalab-stac-catalog) to run it.
