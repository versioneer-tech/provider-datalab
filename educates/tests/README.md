### Unit Testing

You can unit-test your Crossplane Composition locally with `crossplane render`, feeding it observed and required resources to validate the pipeline without touching a live cluster. The loop below renders actual outputs and compares them to golden files with `dyff`, which is easy to drop into CI to catch regressions early.

```sh
for i in {1..1}; do
  crossplane render "educates/tests/base/l00${i}.yaml"     educates/composition.yaml     educates/dependencies/10-functions.yaml     --observed-resources "educates/tests/observed/l00${i}.yaml"     --required-resources "educates/tests/environmentconfig.yaml"     -x > "educates/tests/results/l00${i}.yaml"
  dyff between "educates/tests/results/l00${i}.yaml" "educates/tests/expected/l00${i}.yaml" -s
done
```
