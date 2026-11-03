# ADR-001: Use Datalab as the capability contract

> Written: 02.12.2025. Revised: 03.11.2026.

## Status

Accepted.

## Context

Educates provided browser workspaces with an editor, terminal, and persistent
storage. It was a large dependency for that purpose. Other session tools,
including JupyterLab and OpenShell, use different deployment models. A common
session interface would add backend integration and maintenance work to
Provider Datalab.

The stable Datalab API must focus on storage access, managed data services,
and virtual clusters. Higher level systems can select runtimes and manage
session access and lifetime. Shared systems such as JupyterHub or an OpenShell
gateway can serve tenant sessions without a separate deployment in each
Datalab namespace.

This scope follows [issue #5: Remove Educates and session support](https://github.com/versioneer-tech/provider-datalab/issues/5).

## Decision

The namespaced `Datalab` resource defines team membership, data services, and
named virtual Kubernetes clusters. Crossplane owns the generated service
namespace, quota, control-plane PVCs, identity resources, and service configuration.

Provider Datalab must not provide or manage a session runtime. Do not add a
replacement session backend or a session plugin framework.

Higher level components own sessions, editors, terminals, and task scheduling.
They consume Datalab connections and can use its virtual Kubernetes APIs.
Users can also deploy tools such as code-server or JupyterLab in a virtual
cluster. Those applications do not make session management part of the
Datalab API.

User choices belong in the Datalab spec. Operator policy belongs in the
EnvironmentConfig: identity endpoints, routing, network ranges, allowed
storage classes, and defaults. Platform RBAC and admission control who may
change those settings.

Connection metadata belongs in `status.connections`. Credentials remain in
referenced Secrets and are resolved only by authorized consumers. Generated
Pod names and internal controller resources are not client discovery APIs.

## Consequences

Clients use one capability resource and non-secret connection metadata.
The composition has one owner for generated resources and their deletion
order. Runtime applications can change independently of core data services.
Operators remain responsible for backups, isolation, credentials, and service
availability.

Upgrades from an Educates-based release can delete session resources, PVCs,
and the session registry. Services use the Datalab-named namespace; existing
volumes and data are not moved automatically. Back up data and migrate client
workloads before changing the package or composition. Check the new service
connections before removing the previous installation.
