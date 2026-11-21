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
changing either file.

| Script | Use |
| --- | --- |
| `scripts/vcluster-credentials.py` | Credentials for downloaded kubeconfigs: caller tokens and device login. |
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

The Configuration package contains `composition.yaml`, `xrd.yaml`, and
`crossplane.yaml`. Source templates are not packaged as separate resources.

Integration can build a separate artifact with a Python TTL default:

```bash
python3 scripts/build-composition.py --response-ttl 1m --output /tmp/datalab-it-composition.yaml
```

A TTL override requires a separate output file. It does not change the
environment or auto-ready TTLs, `composition/settings.yaml`, or the normal
deployment artifact. An environment value takes precedence over this default.

`vcluster/sandbox-install.yaml` contains the Agent Sandbox CRDs and supporting
resources. `vcluster/sandbox-controller.yaml` contains its Deployment, with
resource limits, health probes, and a non-root security context. Their headers
record the source release and checksum. Virtual cluster startup applies both
inside the virtual API. EnvironmentConfig `images.sandbox` selects the controller
image; `images.sandboxd` selects the runtime image in SandboxTemplates. Check
controller compatibility when changing its image or CRD schema.

`vcluster/sandbox-template.yaml` and `vcluster/sandbox-pool.yaml` define the
task runtime and pool. See [ADR-001](../docs/architecture/0001-use-the-datalab-crd-as-the-workspace-contract.md#keep-session-storage-independent-of-workloads)
for session storage and lifecycle ownership.
