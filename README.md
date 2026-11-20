<h1><img src="docs/imgs/logo.png" height="48" alt="Versioneer logo" /> Provider Datalab</h1>

[![Tests](https://github.com/versioneer-tech/provider-datalab/actions/workflows/pr.yaml/badge.svg?branch=main&event=push)](https://github.com/versioneer-tech/provider-datalab/actions/workflows/pr.yaml)
[![Package version](https://img.shields.io/github/v/tag/versioneer-tech/provider-datalab?include_prereleases&sort=semver&label=package)](https://github.com/versioneer-tech/provider-datalab/pkgs/container/provider-datalab)
[![License](https://img.shields.io/github/license/versioneer-tech/provider-datalab)](LICENSE)

Provider Datalab provisions virtual Kubernetes clusters, shared data,
container registries, and databases for a team.
Declare users and services in a `Datalab`; Crossplane creates them from the
platform's access, network, and storage settings.

Each Datalab represents one team. The `datalab` composition creates a
same-named service namespace with quotas, resource defaults, and network
policies.

Each virtual cluster includes Agent Sandbox CRDs, its controller, and a
`sandboxd` template. Named sessions keep workspace PVCs independent of workload
Pods. Use Kubernetes port-forwarding for access.

> [!NOTE]
> Development continues on `main` with `versioneer.at/v1`.
> The `legacy` branch maintains the latest `0.12.x` releases, the last series
> with direct Educates support and limited to `pkg.internal/v1beta2`.

```yaml
apiVersion: versioneer.at/v1
kind: Datalab
metadata:
  name: s-jeff
  namespace: workspace
spec:
  users: [jeff, jim, jane]
  vclusters:
    vc0:
      storage: 5Gi
  databases:
    pg0:
      names: [results]
      storage: 1Gi
```

Use a downloaded kubeconfig and a user login or access token to connect to a
virtual cluster.

## Get started

Requires Crossplane 2.4.3 or later in the v2 series. See the
[installation guide](docs/how-to-guides/installation.md) for dependencies and setup.
Operators can set shared defaults and Python response TTLs in EnvironmentConfigs.

[Read the documentation online](https://provider-datalab.versioneer.at/), or use
the guides in this checkout:

| Task | Guide |
| --- | --- |
| Install the package and set platform defaults | [Installation](docs/how-to-guides/installation.md) |
| Run workloads and manage virtual clusters | [Virtual clusters](docs/how-to-guides/vcluster.md) |
| Run sandboxd and keep workspace PVCs | [Sandboxes](docs/how-to-guides/sandboxes.md) |
| Find service credentials and bind Secrets | [Connections](docs/how-to-guides/connections.md) |
| Configure sign-in, machine access, and OAuth2 discovery | [Authentication](docs/how-to-guides/authentication.md) |
| Use databases, share files, and push images | [Use a Datalab](docs/how-to-guides/usage_concepts.md) |
| Read object storage with AWS tools | [S3 access](docs/how-to-guides/s3-access.md) |
| Review permissions or look up fields | [Security](docs/security/index.md), [API reference](docs/reference-guides/api.md) |

See [examples/base](examples/base) for complete Datalab manifests and
[Additional services](docs/how-to-guides/additional_services.md) for Dask,
MLflow, and psql examples.

## Local checks

Use the [CI check selection](tests/README.md#select-checks) for local changes.
Documentation-only changes use the documentation checks. Code and runtime
changes need the full suite below, with Docker running:

```bash
python3 -m pip install -r scripts/requirements.txt
python3 scripts/build-composition.py
bash tests/unit.bash
pre-commit run --all-files
```

Edit the Python steps in `composition/` and the manifests in `templates/`, then
rebuild `composition.yaml`. See [Manifest templates](templates/README.md) for
the source layout and embedded scripts.

See [Unit tests](tests/README.md) for fixtures and focused checks, and
[Integration tests](tests/integration/README.md) for the dedicated Kind cluster.

## License

[Apache License 2.0](LICENSE).
