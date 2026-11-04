# Unit tests

The unit suite renders the composition with `crossplane render` and compares
its output with snapshots through `dyff`. It also checks Data exposure,
credential rotation, network rules, and environment-controlled settings.
Virtual API checks require one workspace OAuth2 client, only the default
`ws_api` account grant, scope mappings for all configured roles, and profile
Secrets without credentials. They also check upgrade resource removal and
connection readiness without profile clients or credentials. Helper checks
cover human token files, separate machine credentials, and missing sources.
OAuth2 discovery checks cover client names, source readiness, stale entry
removal, the unique-name list schema, and separation from service connections.
It does not use a Kubernetes cluster.

Credential checks preserve the generated service passwords. Harness checks
reject false network-isolation results. Session state and PVC behavior are
covered by the rendered examples. Snapshots omit generated owner references,
framework conditions, and resource references that repeat the resource list.
They retain resource specs, readiness rules, and session status.

Backup checks cover positive, zero, and omitted storage quantities for
PostgreSQL, MongoDB, and Redis. They check that PostgreSQL stays available
without backups and that a failed export keeps completed backups. Redis
checks also reject an invalid snapshot before it replaces an older backup.

The TTL checks run generated Python steps in the same function container
and call auto-ready through its function service.
They check the default and a changed build setting with store-enabled and
early-return inputs. They check the separate one-minute integration build without changing the
deployment default. They also reject invalid durations and functions whose
TTL is not configured by the build. Render checks do not measure live timing.

## Run the suite

Docker must be running for render and function checks.
Install the [build dependencies and generate the composition](../templates/README.md)
before running the suite. It rejects a generated composition that differs
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
before updating its expected snapshot. Review intended output changes. Run the full
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
| `003` | `datalab-custom` | vCluster session, named virtual cluster, read-only Data, PostgreSQL |
| `004` | `datalab-custom` | Started and stopped sessions, file bundles, workspace PVCs |

For API or composition changes, use an existing scenario when it covers the
required behavior. Add a scenario only for a missing observable outcome.

Virtual cluster checks cover two independent instances, profile Secrets,
instance removal and session coexistence. They also check built-in admin
profiles, Datalab member grants, and compatibility with explicit admin entries.
Kubernetes admission checks invalid
store names in the integration profile. Live routing,
streaming, persistence, and the STAC catalog are checked by `verify-vcluster`.
