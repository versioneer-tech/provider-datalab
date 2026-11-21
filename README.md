<h1><img src="docs/imgs/logo.png" height="48" alt="Versioneer logo" /> Provider Datalab</h1>

[![Tests](https://github.com/versioneer-tech/provider-datalab/actions/workflows/pr.yaml/badge.svg?branch=main&event=push)](https://github.com/versioneer-tech/provider-datalab/actions/workflows/pr.yaml)
[![Package version](https://img.shields.io/github/v/tag/versioneer-tech/provider-datalab?include_prereleases&sort=semver&label=package)](https://github.com/versioneer-tech/provider-datalab/pkgs/container/provider-datalab)
[![License](https://img.shields.io/github/license/versioneer-tech/provider-datalab)](LICENSE)

Provider Datalab gives teams a shared workspace on Kubernetes.
Declare a team's users, volumes, and services in a `Datalab` resource; Crossplane
creates them from the platform's identity, network, and storage settings.

> [!NOTE]
> The `main` branch uses `versioneer.at/v1`.
> The `legacy` branch maintains the latest `0.12.x` releases, the last series
> with direct Educates support and limited to `pkg.internal/v1beta2`.

## Get started

[Read the documentation](https://provider-datalab.versioneer.at/) or open its
[local index](docs/index.md). Start with the
[installation guide](docs/how-to-guides/installation.md) for platform setup and
[Use a Datalab](docs/how-to-guides/usage_concepts.md) for team workflows.
Complete manifests are in [examples/base](examples/base).

## Development

See [Manifest templates](templates/README.md) for source and build instructions,
[Tests](tests/README.md) for required checks, and
[Integration tests](tests/integration/README.md) for live validation.

## Security

See [Security](SECURITY.md) for access controls, network setup, and backup permissions.

## License

[Apache License 2.0](LICENSE).
