### Unit Testing

You can unit-test your Crossplane v2 Composition locally with `crossplane render`, feeding it observed and required resources to validate the pipeline without touching a live cluster. The loop below renders actual outputs and compares them to golden files with `dyff`, which is easy to drop into CI to catch regressions early.

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