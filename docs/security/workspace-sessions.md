# Workspace Sessions as Sandboxes

A Datalab session is a sandbox made from several boundaries at once: a
container, a Kubernetes namespace, optional vcluster API access, RBAC, mounted
credentials, persistent volumes, NetworkPolicy, and ingress policy. Operators
should describe that combined boundary clearly, because users experience one
workspace while the platform governs many controls behind it.

A Pod is a useful starting point, but it is not a VM. Privileged containers,
host namespaces, broad capabilities, hostPath mounts, runtime sockets, broad
PVCs, mounted secrets, and open networking can all widen the sandbox.

## Session Authority

The effective authority of a Datalab session is the combination of:

- `spec.security.policy`: `restricted`, `baseline`, or `privileged`
- `spec.security.kubernetesAccess`: whether a Kubernetes token is mounted
- `spec.security.kubernetesRole`: `view`, `edit`, or `admin`
- exposed object-storage and service credentials
- writable PVCs and object-storage prefixes
- Docker or registry access
- network ingress and egress policy
- delegated ingress authentication and authorization

With `spec.vcluster: false`, workloads run directly in the Datalab runtime
namespace. With `spec.vcluster: true`, users also get a virtual Kubernetes API,
but workloads still run as Pods in the host cluster and remain subject to host
namespace policy.

## Example Trust Levels

| Example | Runtime boundary | Security signal | Assessment |
| --- | --- | --- | --- |
| `s-jeff` (`002-lab.yaml`) | Host namespace, no pre-created session | `kubernetesAccess: false`, registry disabled, default `baseline` | Good store-validation shape. A started session can use exposed service credentials but cannot call the Kubernetes API. |
| `s-joe` / `s-john` | Host namespace | Default `baseline`, default token with `edit` | Convenient for trusted automation. Stricter installs should override token defaults when API access is unnecessary. |
| `s-jane` (`003-lab.yaml`) | vcluster plus host namespace policy | `privileged`, registry enabled, vcluster `admin` | Useful for trusted build-heavy workflows. Treat privileged mode and registry writes as explicit operator exceptions. |

## User-Facing Contract

Users do not need to understand every generated resource, but the platform
should make these boundaries clear before the workspace is used:

- what the workspace can read and write
- whether Kubernetes API access is available
- whether internet access is open or restricted
- whether Docker, registry, or privileged mode is enabled
- what persists after stop or delete
- what the operator backs up or retains
