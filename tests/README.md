# Unit tests

The unit suite renders the composition with `crossplane render` and compares
its output with snapshots through `dyff`. It also checks Data exposure,
credential rotation, network rules, and environment-controlled settings.
It does not use a Kubernetes cluster.

Credential checks preserve the generated service passwords. Harness checks
reject false network-isolation results and replace certificates for the wrong
hostname. Session state and PVC behavior are covered by the rendered examples.

Backup checks cover positive, zero, and omitted storage quantities for
PostgreSQL, MongoDB, and Redis. They check that PostgreSQL stays available
without backups and that a failed export keeps completed backups. Redis
checks also reject an invalid snapshot before it replaces an older backup.

The TTL checks run generated Python steps in the same function container
and call auto-ready through its function service.
They check the default and a changed build setting with store-enabled and
early-return inputs. They also reject invalid durations and functions whose
TTL is not configured by the build. Render checks do not measure live timing.

## Run the suite

Docker must be running. Use Crossplane CLI `v2.4.1` when updating snapshots;
other versions can change framework status and owner metadata.
Install the [build dependencies and generate the composition](../templates/README.md)
before running the suite. It rejects a generated composition that differs
from its Python and YAML sources.

```bash
bash tests/unit.bash
pre-commit run --all-files
```

To check one example, use `bash tests/unit.bash 001`. This example also runs
the Data and S3 behavior checks. Example `002` also runs the backup checks.
Actual renders are written to `/tmp`. Expected snapshots are tracked in
`tests/expected/`.
Review intended output changes before updating a snapshot. Run the full
unit suite after source changes and build the docs after documentation changes.
See [Integration tests](integration/README.md) for cluster checks.

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
| `001` | `datalab` | Data without sessions, default environment, credential rotation |
| `002` | `datalab` | Default environment selection, writable Data, managed stores |
| `003` | `datalab-custom` | vCluster session, read-only Data, PostgreSQL |
| `004` | `datalab-custom` | Started and stopped sessions, file bundles, workspace PVCs |

For API or composition changes, use an existing scenario when it covers the
required behavior. Add a scenario only for a missing observable outcome.
