# ADR-003: Isolate teams and bind service Secrets

> Written: 03.11.2026.

## Status

Accepted.

## Context

Teams need Kubernetes access for applications, controllers, and CRDs without
host cluster administration. They also need selected credentials in specific
application namespaces. These credentials can come from a Datalab service or
an existing host Secret, for example in `workspace`.

Each service publishes its own connection. Data receives a storage-only
copy in its host service namespace. OAuth proxy and virtual API credentials
remain separate.

Selecting fewer keys does not reduce the backend account's permissions. The
current PostgreSQL output still uses `postgres`. Applications that need less
access must use a suitable account, supplied through an approved host Secret
or created by the application's setup process. Application deployment owns
database accounts and grants. Secret bindings deliver the resulting credentials.

## Decision

### Use a Datalab as the team boundary

Give each team its own Datalab, host service namespace, membership, and
connections. When the team needs Kubernetes workloads, use one named virtual
cluster by default. Applications use namespaces inside it. Add another
instance for separate administration, environments, or trust needs. A team
that only needs managed data services does not need a virtual cluster.

A virtual API lets the team manage its own namespaces, CRDs, controllers,
and virtual cluster roles. Unrelated teams must not share a virtual
administrator. Namespaces alone cannot isolate cluster-scoped CRDs or
virtual administrators. Each instance has separate API state, control-plane
storage, identity profiles, and lifecycle.

Workloads still share host nodes and kernels. The platform must enforce Pod
security, admission, storage restrictions, network access, and quotas on the
host. Virtual control planes do not replace these controls. See the Kubernetes
[tenancy model](https://kubernetes.io/docs/concepts/security/multi-tenancy/#virtual-control-plane-per-tenant).

### Approve sources outside the tenant request

The operator defines exports in `EnvironmentConfig.data.secretExports`.
Each export selects one host `secretRef` or one service `connection` from the
requesting Datalab. It lists the permitted keys and exact claim namespace,
Datalab, virtual instance, and virtual namespace targets. No export grants
access by default.

A tenant binding selects an export alias. It cannot name an arbitrary host
Secret or change the approved source. Platform authorization must protect
both export policy and EnvironmentConfig selection. Never export provider
credentials, backup administration, main OAuth credentials, or private
virtual API recovery credentials. Service-account token Secrets are rejected.

The host source can be outside the Datalab claim namespace. An observe-only
provider Object reads it using the host provider configuration. It never
updates or deletes that source. Tenant changes cannot flow back to it.

### Configure bindings beside virtual access groups

Each entry under `spec.vclusters.<instance>.secretBindings` selects an export,
a virtual namespace, a target Secret name, and a source-to-target key map:

```yaml
spec:
  vclusters:
    vc0:
      groups:
      - name: readers
        namespace: demo
        role: view
      secretBindings:
        catalog-database:
          export: analytics-reader
          target:
            namespace: demo
            name: catalog-database
          keys:
            url: DATABASE_URL
```

The operator's `analytics-reader` export approves the source and this target.
Only its selected `url` key is delivered as `DATABASE_URL`. Two bindings cannot
use the same instance, namespace, and Secret name. Missing or unapproved
sources and keys never produce an empty credential Secret.

Use the existing per-instance provider-kubernetes configuration to create and
observe the virtual Secret. This supports key selection and delivery status
without a general Secret reflector. Native vcluster host Secret import stays
disabled. The provider creates a needed virtual namespace and preserves it
when the binding is removed.

The target name is reserved for the binding. A virtual admission policy
checks the binding ownership label on creation, update, and deletion. The
provider waits for this policy before writing the Secret. An unrelated
existing Secret cannot be adopted. Crossplane Usages keep the protection
resources until the target has been removed.

### Track delivery and keep rotation separate from revocation

`status.secretBindings` reports each export, instance, target, readiness, and
reason. `SecretBindingsReady` summarizes delivery. Status contains no
credentials. A source update changes the selected target keys. Readiness
requires the source to be current and the target to contain the current data.
A source outage retains the last managed copy and reports not ready.

Removing a binding or revoking its export removes the managed target and
source observer. It leaves the source, namespace, application data, and other
instances intact. Removing a Secret cannot revoke values already read by a
workload. Revoke the backend identity when access must end; this can also
require closing active connections. Applications must reload credential files
or restart. Environment variables do not update in a running process.

## Security limits

The target is a managed copy. Virtual RBAC controls who can read or change
it. Reconciliation restores its data but does not stop a virtual administrator
from changing admission or RBAC. A user who can create Pods in a namespace
can usually mount that namespace's Secrets. Use separate namespaces and
suitable workload admission. Use separate Datalabs where virtual
administrators are not mutually trusted. See Kubernetes
[RBAC guidance](https://kubernetes.io/docs/concepts/security/rbac-good-practices/#workload-creation).

Mount Secret files read-only. This does not make database or storage access
read-only; the backend identity must grant those permissions. Keep mutable
target Secrets for rotation instead of treating `immutable: true` as access
control.

provider-kubernetes records Secret data in host Object resources as well as
in the destination API. Those Objects, function traffic, backups, and virtual
control-plane storage need credential-level protection. Restrict access,
configure storage encryption, and keep values out of logs and audit request
bodies. Base64 is an encoding, not encryption. See
[Secret handling](https://kubernetes.io/docs/concepts/security/secrets-good-practices/).

## Consequences

Teams administer their virtual APIs independently. Applications receive
explicit credentials without an aggregate Datalab Secret. The platform owns
export policy and delivery; applications own credential use and reload.
Additional virtual control planes need resources, upgrades, backup, and recovery.

Limited backend identities remain a service-specific requirement. See
[connection configuration](../how-to-guides/connections.md) for export policy,
bindings, and delivery status.
