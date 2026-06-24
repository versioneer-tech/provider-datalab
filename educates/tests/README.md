### Unit Testing

You can unit-test your Crossplane v2 Composition locally with `crossplane render`, feeding it observed and required resources to validate the pipeline without touching a live cluster. The loop below renders actual outputs and compares them to golden files with `dyff`, which is easy to drop into CI to catch regressions early.

### Required practice in this repo

- `crossplane render` requires Docker running locally.
- Any change to `xrd.yaml` or `educates/composition.yaml` must be covered by at least one updated test scenario (`examples/base/00*-lab.yaml`).
- For those changes, update the corresponding golden files in `educates/tests/expected/` after validating the rendered diff.
- Run `pre-commit run --all-files` at the end of each change cycle.
- The live integration probe manifests live under `examples/checks/`: `probe-env-template.yaml` remains templated, while the backend probe Pods are plain manifests applied with `kubectl -n <runtime-namespace>`.

```sh
for file in examples/base/00*-lab.yaml; do
  name="$(basename "$file")"
  idx="${name#00}"
  idx="${idx%-lab.yaml}"

  crossplane render "$file" educates/composition.yaml educates/dependencies/functions.yaml \
    --required-resources "educates/tests/environmentconfig.yaml" \
    -x \
    > "educates/tests/00${idx}-lab.yaml"

  dyff between \
    "educates/tests/00${idx}-lab.yaml" \
    "educates/tests/expected/00${idx}-lab.yaml" \
    -s

  obs="educates/tests/observed/00${idx}-lab.yaml"
  if [[ -f "$obs" ]]; then
    crossplane render "$file" educates/composition.yaml educates/dependencies/functions.yaml \
      --required-resources "educates/tests/environmentconfig.yaml" \
      --observed-resources "$obs" \
      -x \
      > "educates/tests/00${idx}x-lab.yaml"

    dyff between \
      "educates/tests/00${idx}x-lab.yaml" \
      "educates/tests/expected/00${idx}x-lab.yaml" \
      -s
  fi
done
```

### Local sandbox benchmark

Run the local end-to-end benchmark when NetworkPolicy or sandbox hardening
changes need dataplane proof, not only rendered manifests. This is an operator
validation tool: it proves that the selected CNI and Kyverno setup enforce the
policy contract that users and governance reviewers rely on.

```sh
RECREATE_CLUSTER=1 KEEP_CLUSTER=1 ./scripts/benchmark-datalab-sandbox.sh
```

The script creates a dedicated kind cluster with kind's default CNI disabled,
installs Calico for NetworkPolicy enforcement, installs Kyverno, applies the
Datalab-style external-egress and no-external-egress policy modes, and records
traffic/admission timings in `/tmp/provider-datalab-sandbox-benchmark.tsv`.
Override `POD_CIDR`, `SERVICE_CIDR`, `EXTERNAL_URL`, `ITERATIONS`, or image and
chart versions through environment variables when the local cluster shape needs
to match another target.
