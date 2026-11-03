# Unit tests

The unit suite renders the composition with `crossplane render` and compares
its output with snapshots through `dyff`. It also checks Data exposure,
credential rotation, selected virtual Secret bindings, network rules, and
environment-controlled settings.
It does not use a Kubernetes cluster.

The checks cover:

- Data exposure, network denial, environment defaults, and credential rotation.
- Separate service connections, delivery status, and virtual cluster isolation.
- Approved Secret sources, selected keys, rotation, denial, outages, conflicts,
  and binding removal.
- Backup enablement and preservation of completed archives after an export
  failure or an invalid Redis snapshot.
- Response TTL defaults and test overrides on all generated steps.

Snapshots omit generated owner references, framework conditions, and resource
references that repeat the resource list. They retain resource specs,
readiness rules, and connection status.

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

Use `bash tests/unit.bash fast` for helper, quantity schema, duration, and
harness checks without Docker. Install `scripts/requirements.txt` first.

To check one example, use `bash tests/unit.bash 001`. This example also runs
`exposure.py` for Data and S3 settings. Example `002` runs `backups.py` and
`stores.py`. Example `003` runs `settings.py` for environment precedence.
These checks share the render function in `render.py`.
Actual renders are written to `/tmp`. Expected snapshots are tracked in
`tests/expected/`.
Normalize a new render with `python3 tests/render.py /tmp/rendered.yaml`
before updating its expected snapshot. Review the output changes. Run the
full unit suite after changes and build the docs after documentation changes.
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
| `001` | `datalab` | Independent Data, default environment, credential rotation |
| `002` | `datalab` | Default environment selection, writable Data, managed stores |
| `003` | `datalab-custom` | Named virtual clusters, read-only Data, PostgreSQL |
| `004` | `datalab-custom` | Read-only Data and custom namespace policy |

For API or composition changes, use an existing scenario when it covers the
required behavior. Add a scenario only for a missing observable outcome.

The `verify-vcluster` integration profile checks API admission, live routing,
streaming, persistence, and the STAC catalog.
