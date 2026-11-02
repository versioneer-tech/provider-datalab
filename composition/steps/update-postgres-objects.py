# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

from crossplane.function.proto.v1 import run_function_pb2 as fnv1
from google.protobuf import json_format as _json_format


def _to_dict(struct):
    return (
        {}
        if struct is None
        else _json_format.MessageToDict(struct, preserving_proto_field_name=True)
    )


def _extract_manifest(objres):
    if not objres or not getattr(objres, "resource", None):
        return {}
    od = _to_dict(objres.resource)
    atp = (od.get("status") or {}).get("atProvider") or {}
    m1 = atp.get("manifest") or {}
    m2 = (atp.get("raw") or {}).get("manifest") or {}
    return (m1 or m2) or {}


def _safe_str(v):
    return str(v).strip()


def compose(req: fnv1.RunFunctionRequest, rsp: fnv1.RunFunctionResponse):
    xr = _to_dict(req.observed.composite.resource)
    meta = xr.get("metadata", {}) or {}
    spec = xr.get("spec", {}) or {}

    xr_name = meta.get("name")
    xr_namespace = meta.get("namespace") or "default"

    db_hosts = spec.get("databases") or {}
    if not isinstance(db_hosts, dict) or not db_hosts:
        return

    ctx = _to_dict(req.context)
    env = ctx.get("apiextensions.crossplane.io/environment", {}) or {}

    ingress_env = env.get("ingress") or {}
    ingress_domain = ingress_env.get("domain", "default")

    db_env = env.get("database") or {}
    gateway_env = db_env.get("tlsRoute") or {}

    gateway_parent_name = _safe_str(gateway_env.get("parentName") or "")
    gateway_parent_ns = _safe_str(gateway_env.get("parentNamespace") or "")
    gateway_section = _safe_str(gateway_env.get("sectionName") or "")
    has_gateway_parent = bool(
        gateway_parent_name and gateway_parent_ns and gateway_section
    )

    data_sc_default = _safe_str(db_env.get("storageClassName") or "")
    backup_sc_default = _safe_str(db_env.get("backupStorageClassName") or "")

    users = list(spec.get("users", []) or [])
    admin_user = "postgres"
    other_users = [u for u in users if _safe_str(u) and _safe_str(u) != admin_user]
    users_all = [admin_user] + other_users

    observed = getattr(req.observed, "resources", None) or {}
    env_key = f"workshopenvironment-{xr_name}"
    env_manifest = _extract_manifest(observed.get(env_key))

    educates_status = (env_manifest.get("status") or {}).get("educates") or {}
    workshop_ns = _safe_str(educates_status.get("namespace") or xr_name)

    if not workshop_ns:
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
        dbnames = [_safe_str(x) for x in dbnames if _safe_str(x)]
        if not dbnames:
            continue

        db_storage = _safe_str(host_cfg.get("storage") or "")
        backup_storage = _safe_str(host_cfg.get("backupStorage") or "")
        if not db_storage or not backup_storage:
            continue

        db_storage_class = _safe_str(
            host_cfg.get("storageClassName") or data_sc_default
        )
        backup_storage_class = _safe_str(
            host_cfg.get("backupStorageClassName") or backup_sc_default
        )

        cluster_name = f"{host_key.strip()}"
        cm_name = f"{cluster_name}-init-sql"
        init_sql = "\\set ON_ERROR_STOP on\n\\connect postgres\n"

        cm = _render_template(
            req,
            "postgres/init-sql",
            cm_name=cm_name,
            workshop_ns=workshop_ns,
            init_sql=init_sql,
        )

        data_vcs = {
            "accessModes": ["ReadWriteOnce"],
            "resources": {"requests": {"storage": db_storage}},
        }
        if db_storage_class:
            data_vcs["storageClassName"] = db_storage_class

        repo_vcs = {
            "accessModes": ["ReadWriteOnce"],
            "resources": {"requests": {"storage": backup_storage}},
        }
        if backup_storage_class:
            repo_vcs["storageClassName"] = backup_storage_class

        pg_cluster = _render_template(
            req,
            "postgres/postgres-cluster",
            cluster_name=cluster_name,
            workshop_ns=workshop_ns,
            cm_name=cm_name,
            data_vcs=data_vcs,
            repo_vcs=repo_vcs,
        )

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
                "celQuery": "has(object.status) && has(object.status.instances) && object.status.instances.exists(i, i.name == 'primary' && has(i.readyReplicas) && i.readyReplicas >= 1) && has(object.status.pgbackrest) && has(object.status.pgbackrest.repoHost) && object.status.pgbackrest.repoHost.ready == true",
            },
            watch=True,
        )

        if not has_gateway_parent:
            continue

        hostname = f"{cluster_name}-{workshop_ns}.{ingress_domain}"
        route = _render_template(
            req,
            "postgres/route",
            cluster_name=cluster_name,
            workshop_ns=workshop_ns,
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
