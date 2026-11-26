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
| `scripts/valkey-snapshot.py` | Valkey write pause, RDB capture, snapshots, and retention. |
| `scripts/postgres-snapshot.py` | CloudNativePG cold snapshot requests and completed-backup retention. |
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

The build embeds the steps and templates in `composition.yaml`. Follow the
[build and check commands](../README.md#development) after a source change.
Unit tests, CI, and pre-commit reject a stale build. Local renders without
`spec.crossplane.compositionRef` select the EnvironmentConfig using the
generated Composition's name.

The Configuration package contains `composition.yaml`, `xrd.yaml`, and
`crossplane.yaml`. Source templates are not packaged as separate resources.
The platform must apply `dependencies/rbac.yaml` and EnvironmentConfigs
separately. Volume bindings need the supplied admission policy permissions
before the Composition reconciles them.

A test TTL override requires a separate output file; see
[Build](../README.md#build). It changes the Python default only. An environment
value takes precedence; the other function TTLs stay unchanged.

`volumes/pvc.yaml` defines named host storage. The volume step creates
snapshot schedules from `volumes/backup.yaml`. `scripts/volume-snapshot.py`
uses only the Python standard library. It runs on the host with a scoped
ServiceAccount. Virtual cluster lifecycle changes do not pause these resources.

Virtual PV and PVC records belong to a binding policy. Wait for its observed
UID before creating the PV, then create the PVC. Keep the virtual PV binder
active so it can release these records. Their Object wrappers omit `Delete`;
the policy uses background garbage collection to permit control-plane removal.
The host PVC and backups have a separate lifecycle.
