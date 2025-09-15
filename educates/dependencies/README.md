# Dependencies

These manifests declare the dependencies required for the **`datalab-educates`** Composition. They set up the Crossplane runtime (providers, configs, and permissions) that the Datalab resources rely on.

## Runtime prerequisites

- A Kubernetes cluster with Crossplane **v2.0.2+** installed and healthy.
- **Educates** installed in the cluster. This Composition targets that runtime and was tested with Educates **3.3.3**. Installation instructions are available at: https://educates.dev  
  A vendored installation profile for convenience will be published here *(coming soon)*.
- Cluster DNS/ingress/TLS appropriate for your environment.

## Providers and Functions

This Composition expects the following Crossplane components to be installed (versions are examples — pin to the versions you have validated):

- Providers  
  - `provider-kubernetes` (>= `xpkg.upbound.io/crossplane-contrib/provider-kubernetes:v1.0.0`)  
  - `provider-helm` (>= `xpkg.upbound.io/crossplane-contrib/provider-helm:v1.0.0`)  
  - `provider-keycloak` (>= `ghcr.io/crossplane-contrib/provider-keycloak:v2.7.0`)  

- Functions  
  - `crossplane-contrib-function-python`  
  - `crossplane-contrib-function-environment-configs`  
  - `crossplane-contrib-function-auto-ready`

> Pin exact versions (or digests) and upgrade intentionally.

## Keycloak notes

Identity is managed via **Keycloak** using `provider-keycloak`. You must supply:
- A reachable Keycloak endpoint and credentials (referenced by the **`ProviderConfig`**).
- The **realm name** via `EnvironmentConfig.data.iam.realm`.  
  The provider itself needs sufficient permissions in Keycloak to manage clients, groups, mappers, roles, and memberships in that realm.

## Application order

**Order matters**. Create resources in this sequence so that later objects can reference earlier ones:

1. **RBAC for providers** (if any additional ClusterRoles/Bindings are required)  
2. **DeploymentRuntimeConfigs** (tune provider pod resources/replicas)  
3. **Providers** (install the controllers)  
4. **ProviderConfigs** (wire credentials/identities)  
5. **ManagedResourceActivationPolicies (MRAPs)** (opt-in the managed kinds each provider may reconcile)  
6. **Functions**
20. **EnvironmentConfig** (cluster-specific values such as `iam.realm`, `ingress`, `storage`)  
21. **Composition / XRD** and then your **Datalab** resources

## Best practices

- **Pin versions** of Providers/Functions by exact tag or digest and update them via PRs.
- **Manage secrets** securely (e.g., Sealed Secrets, External Secrets). Do not inline credentials in Git.
- **Health gates**: wait for `ProviderRevision` and `FunctionRevision` readiness before applying `ProviderConfig` / MRAP / XR.
