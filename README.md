# Datalab Provider

This package provides the **Datalab** Composite Resource Definition (XRD) and ready-to-use Crossplane v2 Compositions to provision multi-user, multi-runtime data labs.

✨ For a full introduction, see the [documentation](https://provider-datalab.versioneer.at/).

## API Reference

The published XRD with all fields is documented here:  
👉 [API Reference Guide](https://provider-datalab.versioneer.at/latest/reference-guides/api/)

## Install the Configuration Package

Install the configuration package into your cluster. Providers and functions should typically be managed by your GitOps process.

```yaml
apiVersion: pkg.crossplane.io/v1
kind: Configuration
metadata:
  name: datalab
spec:
  package: ghcr.io/versioneer-tech/provider-datalab/educates:latest
  skipDependencyResolution: true
```

## Environment Configuration

Cluster-specific settings are supplied via an `EnvironmentConfig`. The Datalab composition consumes this in its `prepare-environment` step.

```yaml
apiVersion: apiextensions.crossplane.io/v1beta1
kind: EnvironmentConfig
metadata:
  name: datalab
data:
  iam:
    realm: acme
  ingress:
    class: nginx
    domain: lab.acme.com
    secret: wildcard-tls
  storage:
    endpoint: https://s3.acme.com
    force_path_style: "true"
    provider: Other
    region: acme
    secretNamespace: datalab
    type: s3
  defaults: # whole block / all indivudal entries are optional
    quota:
      memory: 2Gi
      storage: 1Gi
      budget: medium
    security:
      policy: baseline
      kubernetesAccess: true
      kubernetesRole: edit
```

## Datalab Spec

### Minimal example

```yaml
apiVersion: pkg.internal/v1beta1
kind: Datalab
metadata:
  name: acme
  namespace: datalab
spec:
  users:
  - alice
  sessions:
  - default
```

If `spec.quota` or `spec.security` are omitted, values fall back to  
`EnvironmentConfig.data.defaults` and then to hard defaults  
(`memory=2Gi`, `storage=1Gi`, `budget=medium`,  
`policy=baseline`, `kubernetesAccess=true`, `kubernetesRole=edit`).  
When `policy=privileged`, Docker is automatically enabled with `storage: 20Gi`.

### More examples

See these [`example manifests`](examples/base) for complete scenarios, including:
- Datalabs without sessions (no runtime started by default).
- Datalabs with sessions and optional vcluster isolation.
- Datalabs with workshop files fetched from Git, OCI images, or HTTP archives.

## Storage Credentials

The `storage` section in the `EnvironmentConfig` references a Kubernetes Secret — named identically to the Datalab — which must already exist in the cluster.  
This Secret must reside in the namespace specified by `storage.secretNamespace` and include at least the following keys:

- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`

The values must provide access to the storage endpoint listed in `EnvironmentConfig.data.storage` (e.g. `endpoint`, `region`, `provider`).

You can create this secret manually, for example:

```bash
kubectl -n datalab create secret generic <DATALAB> \
  --from-literal=AWS_ACCESS_KEY_ID=<KEY_ID> \
  --from-literal=AWS_SECRET_ACCESS_KEY=<SECRET>
```

## License

Apache 2.0 (Apache License Version 2.0, January 2004)  
<https://www.apache.org/licenses/LICENSE-2.0>
