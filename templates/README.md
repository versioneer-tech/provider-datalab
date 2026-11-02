# Manifest templates

`composition/pipeline.yaml` sets the step order. Each Python file in
`composition/steps/` handles one task. Resource manifests are in `templates/`,
grouped by service.

Use `templates/common/` for identical Object wrappers and Pod observers.
Keep each service's readiness and watch rules explicit.

Put shared Python functions in `composition/helpers.py` and import them from
the step files. The build embeds each imported helper and its dependencies.
Keep service-specific logic in its step file.

`composition/settings.yaml` sets `responseTTL` for all steps. Use a positive
whole number of seconds (`30s`), minutes (`5m`), or hours (`1h`). The build
sets each Python response TTL before the step body and gives auto-ready the
same TTL. New function types must have build support for their TTL.

Load and validate the environment before resource steps. Observe connection
Secrets before building the Datalab and OAuth2 proxy Secrets. The Data step
uses the desired OAuth2 proxy Secret. Update session status and check resource
readiness last.

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
