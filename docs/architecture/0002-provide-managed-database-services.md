# ADR-002: Provide Managed Database Services

> Written: 10.12.2025. Revised: 03.11.2026.

## Status

Accepted

## Context

Teams need relational databases, document databases, and key-value stores for
their applications and data work. They need to request these capabilities
without deploying database servers or maintaining backup jobs themselves.

The platform operator needs control over storage, access, maintenance, and
recovery. A common service API lets users work independently within those
controls and lets the operator provide defined service guarantees.

## Decision

### Offer services through Datalab

Use the [Datalab API](0001-use-the-datalab-crd-as-the-workspace-contract.md)
to request these managed services:

| Capability | Service | Datalab field |
| --- | --- | --- |
| Relational database with SQL and transactions | PostgreSQL | `spec.databases` |
| Document database | MongoDB | `spec.documentStores` |
| Key-value store and cache | Redis | `spec.cacheStores` |

Crossplane creates the service resources. The installed database operators
manage their workloads. Services belong to the Datalab and continue to run
when an interactive session stops. `status.connections` reports their endpoints
and credential Secret references.

### Keep user configuration small

Users select a service, name it, and set its data storage size. For PostgreSQL,
MongoDB, and Redis, they can also set `backupStorage` to enable backups and size a
separate backup volume:

```yaml
spec:
  databases:
    pg0:
      names:
      - app
      storage: 10Gi
      backupStorage: 30Gi
  documentStores:
    documents:
      storage: 10Gi
      backupStorage: 30Gi
  cacheStores:
    cache:
      storage: 1Gi
      backupStorage: 3Gi
```

A positive `backupStorage` enables PostgreSQL, MongoDB, or Redis backups. Zero or an
omitted value disables them. PostgreSQL uses pgBackRest; MongoDB uses a
composition-managed dump job. Redis uses a composition-managed RDB snapshot
job. A data volume alone is not a backup. The [backup guide](../how-to-guides/usage_concepts.md#backups)
defines the current schedules, retention, and recovery limits.

Users configure the Datalab resource. Crossplane owns the generated resources
and can replace manual changes during reconciliation.

### Assign service operations to the platform operator

Users own their application data, schemas, queries, and requested capacity.
The platform operator owns service deployment, supported configurations,
upgrades, storage classes, access controls, and operational support. Operator
settings come from the platform's
[EnvironmentConfig](../how-to-guides/installation.md#runtime-and-service-defaults).

For enabled backups, the operator must monitor failures and available space,
test restores, and provide a recovery procedure. Users do not need to manage
backup tools or database operator resources.

### Define the guarantees for each offered service

The operator must define the supported availability, backup retention,
acceptable data loss, recovery time, and data deletion rules. These guarantees
depend on the deployed service, storage, and tested recovery procedure.
Setting a backup volume size alone does not establish them.

The service API provides consistent provisioning, persistent storage, and
connection settings. High availability, recovery after loss of the cluster,
and backup retention after Datalab deletion need separate operator provisions.

## Consequences

- Users can request common data services and backups through one resource,
  without a separate database deployment or backup workflow.
- The platform operator has clear responsibility for operations and the
  guarantees offered to users.
- Service data is independent of session state. Its retention still depends
  on Datalab deletion and storage reclaim rules.
- Users select from supported service settings. Other database products or
  configurations need a separate platform decision.
