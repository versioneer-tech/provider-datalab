### Unit Testing

You can unit-test your Crossplane v2 Composition locally with `crossplane render`, feeding it observed and required resources to validate the pipeline without touching a live cluster. The loop below renders actual outputs and compares them to golden files with `dyff`, which is easy to drop into CI to catch regressions early.

```sh
for file in tests/00*-lab.yaml; do
  i=$(basename "$file" | sed -E 's/^00(.+)-lab\.yaml$/\1/')

  crossplane render \
    "tests/00${i}-lab.yaml" \
    educates/composition.yaml \
    educates/dependencies/functions.yaml \
    --observed-resources "educates/tests/observed/00${i}-lab.yaml" \
    --required-resources "educates/tests/environmentconfig.yaml" \
    -x > "educates/tests/00${i}-lab.yaml"

  dyff between \
    "educates/tests/00${i}-lab.yaml" \
    "educates/tests/expected/00${i}-lab.yaml" \
    -s
done
```
