# Manifest templates

`composition/pipeline.yaml` sets the step order. Each Python file in
`composition/steps/` handles one task. Resource manifests are in `templates/`,
grouped by service.

Use `templates/common/` for identical Object wrappers and Pod observers.
Keep each service's readiness and watch rules explicit.

Put shared Python functions in `composition/helpers.py` and import them from
the step files. The build embeds each imported helper and its dependencies.
Keep service-specific logic in its step file.

The build embeds these scripts with `_embedded_script()`. Rebuild after
changing any of them.

| Script | Use |
| --- | --- |
| `scripts/vcluster-credentials.py` | Credentials for downloaded kubeconfigs: caller tokens and device login. |
| `scripts/volume-snapshot.py` | Host CSI snapshot creation and retention. |
| `scripts/vcluster-cleanup.py` | Host Pod cleanup from a Job during hibernation. Uses the Python standard library. |

Crossplane can cache a function response for its TTL. Set the build defaults in
`composition/settings.yaml`:

| Setting | Default | Applies to |
| --- | --- | --- |
| `responseTTL` | `1m` | Python steps |
| `environmentConfigsTTL` | `10m` | Environment selection |
| `autoReadyTTL` | `10m` | Auto-ready |

Operators can override the Python TTL with
`EnvironmentConfig.data.datalab.responseTTL`. Use a positive whole number of
seconds (`30s`), minutes (`5m`), or hours (`1h`). Invalid values stop the step
before it creates resources. New function types need build support for their TTL.

Load and validate the environment before resource steps. Observe connection
Secrets before publishing service and OAuth2 proxy Secrets. The Data step
uses the desired OAuth2 proxy Secret. Publish status before the final resource
and connection readiness checks.

Each `${parameter}` replaces a complete YAML value. Values can be strings,
numbers, booleans, lists, or mappings. The renderer does not evaluate
expressions or replace text inside strings. Compute those values in Python.

After a source change, build the composition and run the unit tests:

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r scripts/requirements.txt
python3 scripts/build-composition.py
bash tests/unit.bash
```

The build embeds the steps and templates in `composition.yaml`. Deploy this
file. Unit tests, CI, and pre-commit reject a stale build.

For a source installation, apply the XRD and generated Composition to the
configured test cluster before creating Datalabs:

```bash
kubectl apply -f xrd.yaml
kubectl apply -f composition.yaml
```

Install dependencies and set the shared environment as described in the
[installation guide](../docs/how-to-guides/installation.md) first.

The Configuration package contains `composition.yaml`, `xrd.yaml`, and
`crossplane.yaml`. Source templates are not packaged as separate resources.
The platform must apply `dependencies/rbac.yaml` and EnvironmentConfigs
separately. Volume bindings need the supplied admission policy permissions
before the Composition reconciles them.

Integration can build a separate artifact with a Python TTL default:

```bash
python3 scripts/build-composition.py --response-ttl 1m --output /tmp/datalab-it-composition.yaml
```

A TTL override requires a separate output file. It does not change the
environment or auto-ready TTLs, `composition/settings.yaml`, or the normal
deployment artifact. An environment value takes precedence over this default.

`volumes/pvc.yaml` defines named host storage. The volume step creates
snapshot schedules from `volumes/backup.yaml`. `scripts/volume-snapshot.py`
uses only the Python standard library. It runs on the host with a scoped
ServiceAccount. Virtual cluster lifecycle changes do not pause these resources.

Keep the virtual PV binder active to bind and release static volume records.
Their Object wrappers omit `Delete`. The composition waits for the virtual
binding policy's observed UID, then creates the PV before its PVC. Deleting
that policy uses background garbage collection so PVC protection cannot hold
the control plane during removal.
These records have no ownership of the host PVC or backups.
