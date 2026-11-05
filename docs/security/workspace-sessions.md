# Session access

A Datalab session runs as a Pod in the host cluster. It can use its storage
and service credentials, workspace PVC, and any other mounted volumes.
Check these permissions together when deciding which code a user may run.

## Kubernetes and container access

The operator controls token availability and the Kubernetes role through
`defaults.security` in the selected EnvironmentConfig. A session with
vCluster enabled gets a virtual Kubernetes API. Its workloads still run on
host Pods under the host's security and network rules. Without vCluster,
the session uses its host namespace directly.

The `privileged` security policy enables Docker. Host mounts, runtime
sockets, broad roles, and privileged containers can give session code access
beyond its namespace. Give this access only to workloads that need it.
See the [configuration reference](../how-to-guides/installation.md#runtime-and-service-defaults)
for the settings and defaults.

## Explain access to users

Tell users which data and services a session can use, whether Kubernetes
and internet access are available, and whether Docker or privileged workloads
are allowed. Explain what survives a stop or deletion, what is backed up,
and who can restore it.

Stopping a Pod or tightening a network rule does not revoke a leaked
credential. Rotate or revoke it at its source. Protect the generated OAuth
Secret as described in [Authentication](../how-to-guides/authentication.md#groups-and-roles).
