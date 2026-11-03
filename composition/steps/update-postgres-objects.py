# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

from crossplane.function.proto.v1 import run_function_pb2 as fnv1

from composition.helpers import (
    _backup_enabled,
    _extract_manifest,
    _string_value,
    _to_dict,
)
from composition.render import _render_template


def compose(req: fnv1.RunFunctionRequest, rsp: fnv1.RunFunctionResponse):
    xr = _to_dict(req.observed.composite.resource)
    metadata = xr.get("metadata", {}) or {}
    spec = xr.get("spec", {}) or {}

    xr_name = metadata.get("name")
    xr_namespace = metadata.get("namespace") or "default"

    db_hosts = spec.get("databases") or {}
    if not isinstance(db_hosts, dict) or not db_hosts:
        return

    context = _to_dict(req.context)
    environment = context.get("apiextensions.crossplane.io/environment", {}) or {}

    ingress_env = environment.get("ingress") or {}
    ingress_domain = ingress_env.get("domain", "default")

    db_env = environment.get("database") or {}
    gateway_env = db_env.get("tlsRoute") or {}

    gateway_parent_name = _string_value(gateway_env.get("parentName") or "")
    gateway_parent_ns = _string_value(gateway_env.get("parentNamespace") or "")
    gateway_section = _string_value(gateway_env.get("sectionName") or "")
    has_gateway_parent = bool(
        gateway_parent_name and gateway_parent_ns and gateway_section
    )

    data_sc_default = _string_value(db_env.get("storageClassName") or "")
    backup_sc_default = _string_value(db_env.get("backupStorageClassName") or "")

    users = list(spec.get("users", []) or [])
    admin_user = "postgres"
    other_users = [
        u for u in users if _string_value(u) and _string_value(u) != admin_user
    ]
    users_all = [admin_user] + other_users

    observed = getattr(req.observed, "resources", None) or {}
    env_key = f"workshopenvironment-{xr_name}"
    environment_manifest = _extract_manifest(observed.get(env_key))

    educates_status = (environment_manifest.get("status") or {}).get("educates") or {}
    workshop_namespace = _string_value(educates_status.get("namespace") or xr_name)

    if not workshop_namespace:
        return

    def emit_obj(key, manifest, readiness=None, watch=True, management_policies=None):
        body = _render_template(
            req,
            "postgres/object",
            key=key,
            xr_namespace=xr_namespace,
            manifest=manifest,
            watch=watch,
        )
        if readiness is not None:
            body["spec"]["readiness"] = readiness
        if management_policies:
            body["spec"]["managementPolicies"] = management_policies
        rsp.desired.resources[key].resource.update(body)

    for host_key in sorted(list(db_hosts.keys())):
        if not isinstance(host_key, str) or not host_key.strip():
            continue

        host_cfg = db_hosts.get(host_key) or {}
        if not isinstance(host_cfg, dict):
            continue

        dbnames = list(host_cfg.get("names") or [])
        dbnames = [_string_value(x) for x in dbnames if _string_value(x)]
        if not dbnames:
            continue

        db_storage = _string_value(host_cfg.get("storage") or "")
        backup_storage = _string_value(host_cfg.get("backupStorage") or "")
        if not db_storage:
            continue
        backup_enabled = _backup_enabled(backup_storage)

        db_storage_class = _string_value(
            host_cfg.get("storageClassName") or data_sc_default
        )
        backup_storage_class = _string_value(
            host_cfg.get("backupStorageClassName") or backup_sc_default
        )

        cluster_name = f"{host_key.strip()}"
        cm_name = f"{cluster_name}-init-sql"
        init_sql = "\\set ON_ERROR_STOP on\n\\connect postgres\n"

        cm = _render_template(
            req,
            "postgres/init-sql",
            cm_name=cm_name,
            workshop_ns=workshop_namespace,
            init_sql=init_sql,
        )

        data_vcs = {
            "accessModes": ["ReadWriteOnce"],
            "resources": {"requests": {"storage": db_storage}},
        }
        if db_storage_class:
            data_vcs["storageClassName"] = db_storage_class

        pg_cluster = _render_template(
            req,
            "postgres/postgres-cluster",
            cluster_name=cluster_name,
            workshop_ns=workshop_namespace,
            cm_name=cm_name,
            data_vcs=data_vcs,
        )

        readiness_query = "has(object.status) && has(object.status.instances) && object.status.instances.exists(i, i.name == 'primary' && has(i.readyReplicas) && i.readyReplicas >= 1)"
        if backup_enabled:
            repo_vcs = {
                "accessModes": ["ReadWriteOnce"],
                "resources": {"requests": {"storage": backup_storage}},
            }
            if backup_storage_class:
                repo_vcs["storageClassName"] = backup_storage_class
            pg_cluster["spec"]["backups"] = _render_template(
                req, "postgres/backups", repo_vcs=repo_vcs
            )
            readiness_query += " && has(object.status.pgbackrest) && has(object.status.pgbackrest.repoHost) && object.status.pgbackrest.repoHost.ready == true"

        if users_all:
            pg_cluster["spec"]["users"] = [
                {"name": admin_user, "databases": dbnames}
            ] + [{"name": u} for u in other_users]

        emit_obj(
            f"db-configmap-{xr_name}-{cluster_name}",
            cm,
            readiness={"policy": "SuccessfulCreate"},
            watch=True,
        )
        emit_obj(
            f"db-postgrescluster-{xr_name}-{cluster_name}",
            pg_cluster,
            readiness={
                "policy": "DeriveFromCelQuery",
                "celQuery": readiness_query,
            },
            watch=True,
        )

        if not has_gateway_parent:
            continue

        hostname = f"{cluster_name}-{workshop_namespace}.{ingress_domain}"
        route = _render_template(
            req,
            "postgres/route",
            cluster_name=cluster_name,
            workshop_ns=workshop_namespace,
            gateway_parent_name=gateway_parent_name,
            gateway_parent_ns=gateway_parent_ns,
            gateway_section=gateway_section,
            hostname=hostname,
            backend_service_name=f"{cluster_name}-primary",
        )

        emit_obj(
            f"db-tlsroute-{xr_name}-{cluster_name}",
            route,
            readiness={
                "policy": "DeriveFromCelQuery",
                "celQuery": "has(object.status) && has(object.status.parents) && object.status.parents.exists(p, has(p.conditions) && p.conditions.exists(c, c.type == 'Accepted' && c.status == 'True') && p.conditions.exists(c, c.type == 'ResolvedRefs' && c.status == 'True'))",
            },
            watch=True,
        )
