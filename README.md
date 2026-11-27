<h1><img src="docs/imgs/logo.png" height="48" alt="Versioneer logo" /> Provider Datalab</h1>

[![Tests](https://github.com/versioneer-tech/provider-datalab/actions/workflows/pr.yaml/badge.svg?branch=main&event=push)](https://github.com/versioneer-tech/provider-datalab/actions/workflows/pr.yaml)
[![Package version](https://img.shields.io/github/v/tag/versioneer-tech/provider-datalab?include_prereleases&sort=semver&label=package)](https://github.com/versioneer-tech/provider-datalab/pkgs/container/provider-datalab)
[![License](https://img.shields.io/github/license/versioneer-tech/provider-datalab)](LICENSE)

Provider Datalab creates team workspaces on Kubernetes. A `Datalab` resource
declares users, virtual clusters, persistent volumes, and data services.
Crossplane creates them with the platform's identity, network, and storage settings.

> [!NOTE]
> The `main` branch uses `versioneer.at/v1`.
> The `legacy` branch maintains the latest `0.12.x` releases, the last series
> with direct Educates support and limited to `pkg.internal/v1beta2`.

## Get started

A platform operator must complete [installation](docs/how-to-guides/installation.md)
first. Team members can then create a Datalab in their claim namespace:

```yaml
apiVersion: versioneer.at/v1
kind: Datalab
metadata:
  name: team-lab
  namespace: workspace
spec:
  users: [joe]
  stores:
    main:
      type: postgres
      storage: 10Gi
      names: [analytics, catalog]
    cache:
      type: valkey
      storage: 1Gi
      names: [sessions, jobs]
```

Use your team's namespace and existing Keycloak usernames. The operator must
supply their storage credentials. This example requests one PostgreSQL instance
with two databases and one Valkey instance. Backups are disabled by default.
See [Use a Datalab](docs/how-to-guides/usage_concepts.md) for access and backup settings.

| Task | Guide |
| --- | --- |
| Install and configure the platform | [Installation](docs/how-to-guides/installation.md) |
| Create a workspace and use its services | [Use a Datalab](docs/how-to-guides/usage_concepts.md) |
| Connect with kubectl and run workloads | [Virtual clusters](docs/how-to-guides/vcluster.md) |
| Bind volumes, take backups, and restore data | [Volumes](docs/how-to-guides/volumes.md) |
| Connect applications to a service | [Connections](docs/how-to-guides/connections.md) |
| Configure login and delegated access | [Authentication](docs/how-to-guides/authentication.md) |

The [documentation site](https://provider-datalab.versioneer.at/) includes the
[API reference](docs/reference-guides/api.md). Complete examples are in
[examples/base](examples/base).

## Development

Edit `composition/`, `templates/`, and the embedded scripts. Rebuild
`composition.yaml` after a source change; do not edit that generated file.
The [template guide](templates/README.md) explains the build and resource layout.

### Setup

Use Python from [.python-version](.python-version), Go from
[.go-version](.go-version), Git, and OpenSSL. The full unit suite also needs
Docker. The tool installer supports Linux AMD64; its versions and checksums
are in [scripts/tools.json](scripts/tools.json).

Run these commands from the repository root:

```bash
python3.13 -m venv .venv
. .venv/bin/activate
python3 -m pip install --only-binary=:all: --require-hashes \
  -r scripts/requirements.txt -r docs/requirements.txt -r tools/requirements.txt
python3 scripts/install-tools.py actionlint gitleaks crossplane dyff
export PATH="$PWD/build/tools:$PATH"
```

Add tools when you need the corresponding task:

| Task | Install command |
| --- | --- |
| Kubernetes integration | `python3 scripts/install-tools.py kind kubectl helm crane` |
| Full unit dependency reports | `python3 scripts/install-tools.py crane trivy govulncheck` |
| Package security scans | `python3 scripts/install-tools.py crane trivy` |
| Generate the API reference | `python3 scripts/install-tools.py crdoc` |

### Build

```bash
python3 scripts/build-composition.py
```

The build combines the pipeline, Python steps, templates, and embedded scripts.
Checks reject a stale generated composition. For a test-specific TTL, use a
separate output file:

```bash
python3 scripts/build-composition.py --response-ttl 1m --output /tmp/datalab-it-composition.yaml
```

This keeps the source defaults unchanged. An EnvironmentConfig TTL takes precedence.

### Checks

Use the same commands locally and in CI:

| Command | What it checks |
| --- | --- |
| `bash tests/checks.bash` | Documentation, workflow syntax, secret detection, generated composition, copyright, and whitespace. No Docker or cluster needed. |
| `bash tests/unit.bash fast` | Python helper and security-policy tests. No Docker needed. |
| `bash tests/unit.bash` | All units, render fixtures, admission rules, and real Keycloak login and token exchange. Needs Docker. |
| `bash tests/integration/run.bash all --kind` | All eight profiles on the dedicated Kind cluster. Run after units pass. |

File checks keep each run's reports under `build/file-security/` and build the
documentation in `build/docs-check/`. Use `mkdocs serve` to preview documentation.
For another Kubernetes target, use the explicit connection and storage options
in the [integration guide](tests/integration/README.md).

The full unit command checks test dependency updates and vulnerabilities before
running fixtures. Reports stay under `build/test-dependencies/`. Review findings
and check failures before using the fixtures. Test-only findings are advisory;
they do not approve a production candidate. Run `bash tests/dependencies.bash`
for these reports alone. Focused and fast unit commands omit this network check.

To select the required checks for a pull request:

```bash
python3 scripts/ci-checks.py --base origin/main
```

Use the actual PR base when known. `docs_only=true` requires file/documentation
checks. Otherwise run the full units, applicable integration, and the
[candidate security checks](SECURITY.md#local-candidate-checks). Markdown,
documentation images, and `mkdocs.yml` can qualify as docs only. Dependency or
unknown files, an empty comparison, or a missing base select all checks.
The comparison includes committed, staged, unstaged, and untracked changes.
Draft PRs defer cluster tests until marked ready; manual CI runs select everything.
The final CI status is `required_checks`.

For focused development, use `bash tests/unit.bash 001` to render one example,
or `python3 -m unittest discover -s tests -p test_credentials.py -v` for one
helper suite. These do not replace the full checks for a runtime change.
See [test coverage and fixtures](tests/README.md) for where to add a regression test.

### Maintain dependencies

Direct Python dependencies are in `.in` files; matching `.txt` files include
locked transitive versions and hashes. For a manual change, regenerate the
affected lock with an installed `uv`, for example:

```bash
uv pip compile --python-version "$(cat .python-version)" --generate-hashes --no-emit-index-url \
  scripts/requirements.in -o scripts/requirements.txt
```

Review the resolved packages and install behavior, then repeat the frozen
install above and run the relevant checks. See the
[dependency policy](SECURITY.md#dependency-updates-and-tool-installation).

Dependabot updates production and build manifests on schedule. Test dependencies
are checked when the full tests run, with no scheduled version updates. Run
`python3 scripts/check-image-updates.py` to report image updates in the other
source formats. Use `--reports <new-directory>` for another run. Scan and test
replacement images before changing their pins. `scripts/components.json` holds
shared platform image pins and checked URLs for charts and bootstrap manifests.
`scripts/components.py` verifies downloaded bytes before installation.
Update the lock and source image defaults together, then run all checks.

On Kind, the full integration run installs a saved Configuration from the
Crossplane offline cache before the service tests. Supply an existing candidate
with `tests/integration/run.bash all --kind --candidate <directory>/datalab.xpkg`.
The check verifies the package digest, installation status, and installed
Composition.

## Cluster prerequisites

Use the [installation prerequisites](docs/how-to-guides/installation.md#prerequisites)
for Crossplane, identity, storage, networking, PostgreSQL, and snapshot setup.

## Health checks

See the [component health checks](SECURITY.md#health-checks) for readiness,
startup, liveness, and their limits.

## Security and releases

See [SECURITY.md](SECURITY.md) for private vulnerability reports, access
boundaries, temporary exceptions, scheduled scans, and the
[release procedure](SECURITY.md#candidate-and-publication).
Use [CONTRIBUTING.md](CONTRIBUTING.md) for pull request guidance.

## License

[Apache License 2.0](LICENSE).
