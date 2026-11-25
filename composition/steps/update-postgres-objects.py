# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

import base64
import hashlib
import hmac
import json
import re

from crossplane.function import response
from composition.helpers import _b64get_any, _resource_name, _stores, _to_dict, require_secret
from composition.render import _render_template

BACKUP_SCRIPT = _embedded_script("scripts/postgres-snapshot.py")


def compose(req, rsp):
    xr = _to_dict(req.observed.composite.resource)
    metadata = xr["metadata"]
    name, namespace = metadata["name"], metadata.get("namespace") or "default"
    spec = xr.get("spec") or {}
    env = _to_dict(req.context).get("apiextensions.crossplane.io/environment") or {}
    config = env.get("database") or {}
    route_config = config.get("tlsRoute") or {}
    users = sorted(set(user for user in spec.get("users") or [] if user not in ("postgres", "datalab")))

    def emit(key, manifest, readiness=None, policies=None):
        body = _render_template(req, "postgres/object", key=key, xr_namespace=namespace,
                                manifest=manifest, watch=True)
        body["spec"]["readiness"] = readiness or {"policy": "SuccessfulCreate"}
        if policies:
            body["spec"]["managementPolicies"] = policies
        rsp.desired.resources[key].resource.update(body)

    def component(value):
        if re.fullmatch(r"[a-z0-9]([-a-z0-9]*[a-z0-9])?", value):
            return value
        return hashlib.sha256(value.encode()).hexdigest()[:16]

    for cluster, database in sorted(_stores(spec, "postgres").items()):
        dbnames = database.get("names") or []
        if not dbnames or not database.get("storage"):
            continue
        storage = {"size": database["storage"]}
        storage_class = config.get("storageClassName")
        if storage_class:
            storage["storageClass"] = storage_class
        manifest = _render_template(
            req, "postgres/postgres-cluster", cluster_name=cluster, runtime_namespace=name,
            storage=storage, database_name=dbnames[0],
            postgres_image=(env.get("images") or {}).get("postgres")
            or "ghcr.io/cloudnative-pg/postgis:17.12-3.7.0-202611231010-standard-trixie",
        )
        source = require_secret(req, rsp, f"postgres-superuser-{name}-{cluster}",
                                cluster + "-superuser", name)
        password = _b64get_any(source.get("data") or {}, ["password"])
        roles = []
        for user in users:
            user_key = component(user)
            secret_name = _resource_name(cluster, "user", user_key)
            secret = require_secret(req, rsp, f"postgres-user-{name}-{cluster}-{user}", secret_name, name)
            data = secret.get("data") or {}
            if not data.get("password") and password:
                # Use private operator entropy; names alone must not determine a password.
                value = hmac.new(password.encode(), f"{name}:{cluster}:{user}".encode(), hashlib.sha256).digest()
                data = {"username": base64.b64encode(user.encode()).decode(),
                        "password": base64.b64encode(base64.urlsafe_b64encode(value).rstrip(b"=")).decode()}
            if data.get("password"):
                emit(_resource_name("db-user-secret", name, cluster, user_key), {
                    "apiVersion": "v1", "kind": "Secret", "type": "kubernetes.io/basic-auth",
                    "metadata": {"name": secret_name, "namespace": name,
                                 "labels": {"cnpg.io/reload": "true"}}, "data": data,
                })
            roles.append({"name": user, "login": True, "passwordSecret": {"name": secret_name}})
        if roles:
            manifest["spec"]["managed"] = {"roles": roles}
        emit(_resource_name("db-network", name, cluster), _render_template(
            req, "postgres/network", cluster_name=cluster, runtime_namespace=name,
            operator_namespace=config.get("operatorNamespace") or "cnpg-system",
        ))

        if database.get("backups") is True:
            snapshot_class = config.get("snapshotClassName") or (env.get("volumes") or {}).get("snapshotClassName")
            count = config.get("maxSnapshots", 4)
            if not isinstance(snapshot_class, str) or not snapshot_class.strip():
                response.fatal(rsp, "PostgreSQL backups require data.database.snapshotClassName or data.volumes.snapshotClassName.")
                return
            if isinstance(count, bool) or not isinstance(count, (int, float)) or count != int(count) or not 1 <= count <= 100:
                response.fatal(rsp, "data.database.maxSnapshots must be an integer from 1 to 100.")
                return
            manifest["spec"]["backup"] = {"target": "primary", "volumeSnapshot": {
                "className": snapshot_class, "online": False, "snapshotOwnerReference": "backup",
            }}
            class_key = _resource_name("db-snapshot-class", name, cluster)
            emit(class_key, {"apiVersion": "snapshot.storage.k8s.io/v1", "kind": "VolumeSnapshotClass",
                             "metadata": {"name": snapshot_class}},
                 {"policy": "DeriveFromCelQuery", "celQuery": "object.deletionPolicy == 'Delete'"}, ["Observe"])
            backup_name = _resource_name("postgres", "snapshot", cluster)
            resources = _render_template(
                req, "postgres/backup", target=name, cluster_name=cluster, backup_name=backup_name,
                backup_binding=_resource_name(name, backup_name), snapshot_class=snapshot_class,
                max_snapshots=str(int(count)), schedule=config.get("schedule") or "0 1 * * *",
                backup_script=BACKUP_SCRIPT,
                backup_image=(env.get("images") or {}).get("volumeSnapshot") or "python:3.13-alpine",
            )["resources"]
            for suffix, resource in resources.items():
                emit(_resource_name("db-backup", name, cluster, suffix), resource)

        query = "has(object.status) && has(object.status.conditions) && object.status.conditions.exists(c, c.type == 'Ready' && c.status == 'True')"
        # CNPG can keep Ready true while a cold backup fences the only instance.
        query += " && (!has(object.metadata.annotations) || !('cnpg.io/fencedInstances' in object.metadata.annotations) || object.metadata.annotations['cnpg.io/fencedInstances'] == '[]')"
        if users:
            query += " && has(object.status.managedRolesStatus) && has(object.status.managedRolesStatus.byStatus) && has(object.status.managedRolesStatus.byStatus.reconciled) && "
            query += " && ".join(json.dumps(user) + " in object.status.managedRolesStatus.byStatus.reconciled" for user in users)
        emit(f"db-cluster-{name}-{cluster}", manifest,
             {"policy": "DeriveFromCelQuery", "celQuery": query})
        for dbname in dbnames:
            if dbname in ("postgres", "template0", "template1"):
                continue
            db_key = component(dbname)
            db_resource = _resource_name(cluster, "database", db_key)
            emit(_resource_name("db-database", name, cluster, db_key), _render_template(
                req, "postgres/database", database_resource=db_resource, database_name=dbname,
                runtime_namespace=name, cluster_name=cluster,
            ), {"policy": "DeriveFromCelQuery", "celQuery":
                "has(object.status) && has(object.status.applied) && object.status.applied == true && has(object.status.observedGeneration) && object.status.observedGeneration == object.metadata.generation"})

        if all(route_config.get(key) for key in ("parentName", "parentNamespace", "sectionName")):
            route = _render_template(
                req, "postgres/route", cluster_name=cluster, runtime_namespace=name,
                gateway_parent_name=route_config["parentName"], gateway_parent_ns=route_config["parentNamespace"],
                gateway_section=route_config["sectionName"],
                hostname=f"{cluster}-{name}.{(env.get('ingress') or {}).get('domain', 'default')}",
                backend_service_name=cluster + "-rw",
            )
            emit(f"db-tlsroute-{name}-{cluster}", route, {"policy": "DeriveFromCelQuery", "celQuery":
                "has(object.status) && has(object.status.parents) && object.status.parents.exists(p, has(p.conditions) && p.conditions.exists(c, c.type == 'Accepted' && c.status == 'True') && p.conditions.exists(c, c.type == 'ResolvedRefs' && c.status == 'True'))"})
