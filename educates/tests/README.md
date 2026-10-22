### Unit Testing

You can unit-test the Composition for Crossplane v2 or later with `crossplane render`. Supply observed and required resources to validate the pipeline without touching a live cluster. The command below renders actual outputs and compares them to golden files with `dyff`, which is easy to use in CI to catch regressions early.

### Required practice in this repo

- `crossplane render` requires Docker running locally.
- Use Crossplane CLI `v2.4.1` when you regenerate the expected render snapshots.
  Other CLI versions can emit different framework-owned status and owner
  metadata even when the composed resource specifications are unchanged.
- Run focused checks during development. Before sign-off, run the full unit
  suite and all integration profiles. Documentation changes need a docs build
  during development.
- Actual render output is written to `/tmp`. Only expected snapshots are tracked.
- Any change to `xrd.yaml` or `educates/composition.yaml` must be covered by at least one updated test scenario (`examples/base/00*-lab.yaml`).
- For those changes, update the corresponding golden files in `educates/tests/expected/` after validating the rendered diff.
- Run `pre-commit run --all-files` at the end of each change cycle.

```sh
tests/unit.bash
```

To check one example, use `tests/unit.bash 001`. Example `001` uses the custom
environment for Gateway and experimental S3 access. Its focused checks also
cover endpoint configuration and storage token rotation.

Live NetworkPolicy checks are part of the `verify-network`
integration profile. The `verify-registry` profile verifies a session registry.
The `verify-data` profile checks file access, credential rotation, and
read-only enforcement. Render tests cover Data resource structure and disabled
Data. The `verify-s3` profile checks the experimental S3 endpoint and shared
browser hostname with the normal Datalab OAuth client.
The `verify-postgres` profile applies a Datalab with PostgreSQL enabled and
verifies internal database access through the generated Datalab Secret.
`verify-mongo`, `verify-redis`, and `verify-qdrant` do the same for managed
document, cache, and vector stores. The profiles are documented in
`tests/integration/README.md`.
