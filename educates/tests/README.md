### Unit Testing

You can unit-test the Composition for Crossplane v2 or later with `crossplane render`. Supply observed and required resources to validate the pipeline without touching a live cluster. The command below renders actual outputs and compares them to golden files with `dyff`, which is easy to use in CI to catch regressions early.

### Required practice in this repo

- `crossplane render` requires Docker running locally.
- Use Crossplane CLI `v2.4.1` when you regenerate the tracked render snapshots.
  Other CLI versions can emit different framework-owned status and owner
  metadata even when the composed resource specifications are unchanged.
- Any change to `xrd.yaml` or `educates/composition.yaml` must be covered by at least one updated test scenario (`examples/base/00*-lab.yaml`).
- For those changes, update the corresponding golden files in `educates/tests/expected/` after validating the rendered diff.
- Run `pre-commit run --all-files` at the end of each change cycle.
- The live integration probe manifests live under `examples/checks/`: `probe-env-template.yaml` remains templated, while the backend probe Pods are plain manifests applied with `kubectl -n <runtime-namespace>`.

```sh
tests/unit.bash
```

Live NetworkPolicy and Kyverno checks are part of the `verify-network`
integration profile. The `verify-registry` profile verifies a session registry.
The `verify-postgres` profile applies a Datalab with PostgreSQL enabled and
verifies internal database access through the generated Datalab Secret. The
profiles are documented in `tests/integration/README.md`.
