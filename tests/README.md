# Unit tests

The suite checks composition output and local helpers. It uses Docker for
`crossplane render` and function calls, and needs no Kubernetes cluster.

## Run the suite

Docker must be running for render and function checks.
Install the [build dependencies and generate the composition](../templates/README.md)
before running the suite. It rejects a generated composition that differs
from its Python and YAML sources.

```bash
bash tests/unit.bash
pre-commit run --all-files
```

Use `bash tests/unit.bash fast` for local helper, schema, duration, and harness
checks without Docker. Install `scripts/requirements.txt` first.

To check one example, use `bash tests/unit.bash 001`. This example also runs
`exposure.py` for Data and S3 settings. Example `002` runs `backups.py` and
`stores.py`. Example `003` runs `settings.py` for environment precedence.
These checks share the render function in `render.py`.
Actual renders are written to `/tmp`. Expected snapshots are tracked in
`tests/expected/`.
Normalize a new render with `python3 tests/render.py /tmp/rendered.yaml`
before updating its expected snapshot. Review each output change. Run the full
unit suite after repository changes, including documentation changes. Build
the docs after documentation changes.

## What the checks cover

Snapshots retain resource specs, readiness rules, and session status. They
omit generated owner references, framework conditions, and resource references
that repeat the resource list. Behavior checks cover outcomes that need more
than a snapshot comparison:

- Virtual clusters: instance isolation and removal, member grants, one
  workspace OAuth2 client with only the default `ws_api` account grant, exact
  human group grants, optional profile scopes, the exchange policy, public
  profile Secrets, and removal of old profile resources.
- Caller credentials and discovery: human token files, separate machine
  credentials, missing sources, readiness, stale entry removal, and no
  credential disclosure in status.
- Service operation: stable generated passwords, credential rotation, Data
  exposure, network rules, and environment overrides.
- Service publication: copies in the Datalab namespace, connection fields,
  local ownership, rotation readiness, source loss and recovery, removal,
  and distinct names for Datalabs with the same service instances.
- Session storage: effective defaults and overrides, retained stopped-session
  storage, exclusion of service volumes, shared-volume counting, known zero,
  and omission of unknown or invalid sizes.
- Backups: enabled and disabled storage settings, usable PostgreSQL without
  backups, retained backups after export failure, and invalid Redis snapshots.
- Function TTL: configured responses on normal and early-return paths, a
  separate integration build, and rejection of invalid build settings.

Render tests cannot prove live authorization, routing, persistence, or timing.
`token-exchange.py` checks rendered authorization boundaries and exchange
enablement after scope reconciliation. It does not simulate token issuance.
It rejects broad client-role mappers and checks role selection per scope.
It also checks policy deletion dependencies.
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
| `001` | `datalab` | Data without sessions, default environment, credential rotation |
| `002` | `datalab` | Default environment selection, writable Data, managed stores |
| `003` | `datalab-custom` | Named virtual cluster, vCluster session, read-only Data, PostgreSQL |
| `004` | `datalab-custom` | Started and stopped sessions, file bundles, workspace PVCs |

For API or composition changes, use an existing scenario when it covers the
required behavior. Add a scenario only for a missing observable outcome.
