# Session access

A Datalab session runs as a Pod in the host cluster. Its access comes from
Kubernetes permissions, credentials, volumes, and network rules. Check these
together when deciding which code a user may run.

## What a session can use

The session can read and write the data allowed by its storage and service
credentials. It can use the mounted workspace PVC and any other volumes made
available to the Pod. Docker, registries, host mounts, or runtime sockets can
add further access.

`spec.security.kubernetesAccess` controls whether the session gets a Kubernetes
token. `spec.security.kubernetesRole` sets its role. With
`spec.vcluster: false`, workloads use the host namespace directly. With
`true`, the session gets a virtual Kubernetes API, while its workloads still
run on host Pods under the host's security and network rules.

`spec.security.policy` selects `restricted`, `baseline`, or `privileged`.
Privileged mode enables Docker. The operator decides who may enable it.

A user or service that can read `<datalab>-oauth2-client` in the runtime
namespace can request machine tokens. Those tokens carry `ws_api`. Browser
access uses the separate `ws_access` and `ws_admin` roles.

## Example settings

| Example | Settings | Access |
| --- | --- | --- |
| `s-jeff` | No session, Data disabled, Kubernetes access disabled | Managed stores run without a workspace. A session added later can use the supplied service credentials. |
| `s-joe` and `s-john` | Host namespace, baseline policy, default `edit` role | Session code can use its Kubernetes token unless the operator changes the default. |
| `s-jane` | vCluster, privileged policy, admin role, registry enabled | Session code has broad permissions. Use only with operator approval. |

The manifests are in `examples/base/`. Their settings are examples, not a
required policy for other Datalabs.

## Explain access to users

Before users start a session, tell them which data and services it can use,
whether Kubernetes and internet access are available, and whether Docker or
privileged workloads are allowed. Explain what survives a stop or deletion,
what is backed up, and who can restore it.

See [Security](index.md) for the platform's responsibilities and
[Network policies](sandbox-controls.md) for egress rules.
