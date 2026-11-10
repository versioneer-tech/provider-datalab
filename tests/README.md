# Unit tests

The suite checks composition output and local helpers. It uses Docker for
`crossplane render` and function calls, and needs no Kubernetes cluster.

## Select checks

[GitHub Actions](../.github/workflows/pr.yaml) defines the required checks.
Use the same classifier locally, against the target branch or pull request
base commit:

```bash
python3 scripts/ci-checks.py --base origin/main
```

Without `--head`, this includes committed, staged, unstaged, and untracked
changes. CI passes `--head` to compare two commits. Markdown files, files under
`docs/`, and `mkdocs.yml` select `docs_only=true`. Other or mixed changes,
empty comparisons, and unavailable base commits select `docs_only=false`.
Manual CI runs select the full checks.

Run the documentation checks below in both cases. When `docs_only=false`,
also run the full unit suite and the applicable integration checks.

## Documentation changes

Install `docs/requirements.txt` and run:

```bash
python3 tests/ci-checks.py
mkdocs build --strict --site-dir /tmp/provider-datalab-docs
pre-commit run --all-files
git diff --check
```

Check changed commands and links in the affected guides. Documentation-only
changes do not need Docker, the full unit suite, a local Keycloak server, or
Kind integration. Use the classifier above when the scope is unclear.

## Run the suite

Install Docker, the Crossplane CLI, `dyff`, OpenSSL, Python, and `pre-commit`.
Docker must be running for render and function checks.
Install the [build dependencies and generate the composition](../templates/README.md)
before running the suite. The suite rejects a generated composition that differs
from its Python and YAML sources.

```bash
bash tests/unit.bash
pre-commit run --all-files
```

Use `bash tests/unit.bash fast` for local helper, schema, duration, and harness
checks without Docker. Install `scripts/requirements.txt` first.

To check one example, use `bash tests/unit.bash 001`. This example also runs
`exposure.py` for Data and S3 settings. Example `002` runs `backups.py` and
`stores.py`. Example `003` runs `settings.py` for environment settings.
These checks share the render function in `render.py`.
Actual renders are written to `/tmp`. Expected snapshots are tracked in
`tests/expected/`.
Normalize a new render with `python3 tests/render.py /tmp/rendered.yaml`
before updating its expected snapshot. Review each output change. Run the full
unit suite after code or runtime changes. Use the documentation checks above
when only documentation changes.

## What the checks cover

Snapshots retain resource specs, readiness rules, and connection status. They
omit generated owner references, framework conditions, and resource references
that repeat the resource list. Behavior checks cover outcomes that need more
than a snapshot comparison:

| Tests | Purpose |
| --- | --- |
| `vclusters.py` | Instance isolation, Sandbox setup, session storage, membership, Secret bindings, public profiles, settings, and removal. Each `check_*` function covers one scenario. |
| `helpers.py` | Stable passwords, backup quantities, caller tokens, device login, private caches, refresh, secret prompts, and local build and harness errors. |
| `token-exchange.py` and `keycloak_policy.py` | Exact group grants, scope restrictions, policy readiness, and issued tokens from a disposable Keycloak server. |
| `oauth2.py`, `s3-connections.py`, and `service-connections.py` | Discovery metadata, credential publication, rotation, source loss and recovery, removal, and distinct connection names. |
| `exposure.py`, `settings.py`, `stores.py`, and `registry.py` | Service access, routes, storage, network rules, quotas, resource defaults, and environment overrides. |
| `backups.py` | Backup enablement, retained archives after export failure, and rejection of invalid Redis snapshots. |
| `response-ttl.py` | Response TTL on normal and early returns, separate integration builds, and invalid build settings. |

Render tests cannot prove live authorization, routing, persistence, or timing.
`token-exchange.py` checks rendered authorization boundaries and exchange
enablement after scope reconciliation. It also uses `keycloak_policy.py` to
check real refresh and token exchange with the rendered identity settings.
The [Kind integration suite](integration/README.md) checks those outcomes.
Its `verify-vcluster` profile also checks OAuth2 name uniqueness through
Kubernetes admission and rejects API access without a vcluster role.

## Fixtures

The Datalab manifests are in [`examples/base/`](../examples/base).
[`environmentconfig.yaml`](environmentconfig.yaml) contains only `datalab`
and `datalab-custom`. The custom profile demonstrates the settings listed in
the [usage examples](../docs/how-to-guides/usage_concepts.md#examples).
Examples and integration routes use `lab.acme.com`. Storage Secret fixtures
use different endpoint names to check that Secret values take precedence over
the environment settings.

| Example | Environment | Main checks |
| --- | --- | --- |
| `001` | `datalab` | Independent Data, default environment, credential rotation |
| `002` | `datalab` | Default environment selection, writable Data, managed stores |
| `003` | `datalab-custom` | Virtual cluster, durable session PVC, sandboxd template, read-only Data, PostgreSQL |
| `004` | `datalab-custom` | Direct services with custom environment settings |

For API or composition changes, use an existing scenario when it covers the
required behavior. Add a scenario only for a missing observable outcome.
