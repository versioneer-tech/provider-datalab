# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

import json
from crossplane.function import request, response
from composition.helpers import _resource_name, _to_dict, _volume_storage_classes
from composition.render import _render_template

BACKUP_SCRIPT = _embedded_script("scripts/volume-snapshot.py")


def compose(req, rsp):
    xr = _to_dict(req.observed.composite.resource)
    meta = xr["metadata"]
    namespace = meta["name"]
    env = _to_dict(req.context).get("apiextensions.crossplane.io/environment") or {}
    config = env.get("volumes") or {}
    status = _to_dict(rsp.desired.composite.resource).get("status") or {}
    references = []
    volumes = (xr.get("spec") or {}).get("volumes") or {}
    needs_snapshots = any(v.get("backups") is True or v.get("restoreFrom") for v in volumes.values())
    if volumes:
        try:
            _, storage_class = _volume_storage_classes(env)
        except ValueError as error:
            response.fatal(rsp, str(error))
            return
    if needs_snapshots:
        snapshot_class = config.get("snapshotClassName")
        if not isinstance(snapshot_class, str) or not snapshot_class.strip():
            response.fatal(rsp, "Named volumes require data.volumes.snapshotClassName.")
            return
        max_snapshots = config.get("maxSnapshots", 2)
        if (isinstance(max_snapshots, bool) or not isinstance(max_snapshots, (int, float))
                or not 1 <= max_snapshots <= 100 or max_snapshots != int(max_snapshots)):
            response.fatal(rsp, "data.volumes.maxSnapshots must be an integer from 1 to 100.")
            return

    def emit(key, manifest, readiness=None):
        body = _render_template(
            req, "common/object", key=key,
            xr_namespace=meta.get("namespace") or "default", manifest=manifest,
            readiness=readiness or {"policy": "SuccessfulCreate"},
        )
        rsp.desired.resources[key].resource.update(body)

    if needs_snapshots:
        observer_key = _resource_name("volume-snapshot-class", namespace)
        emit(observer_key, {
            "apiVersion": "snapshot.storage.k8s.io/v1", "kind": "VolumeSnapshotClass",
            "metadata": {"name": snapshot_class},
        }, {"policy": "DeriveFromCelQuery", "celQuery": "object.deletionPolicy == 'Delete'"})
        rsp.desired.resources[observer_key].resource["spec"].update({"managementPolicies": ["Observe"]})

    for name, volume in sorted(volumes.items()):
        pvc_name = "volume-" + name
        key = _resource_name("volume", namespace, name)
        pvc = _render_template(
            req, "volumes/pvc", target=namespace, pvc_name=pvc_name, volume_name=name,
            storage=volume.get("storage") or config.get("storage") or "1Gi",
        )
        pvc["spec"]["storageClassName"] = storage_class
        if volume.get("restoreFrom"):
            pvc["spec"]["dataSource"] = {
                "apiGroup": "snapshot.storage.k8s.io", "kind": "VolumeSnapshot", "name": volume["restoreFrom"],
            }
        emit(key, pvc)
        policy_name = _resource_name("volume", namespace, name, "claim")
        emit(_resource_name("volume", namespace, name, "claim-policy"), _render_template(
            req, "volumes/claim-policy", namespace=namespace, policy_name=policy_name,
            syncer_expression="request.userInfo.username.startsWith(" + json.dumps("system:serviceaccount:" + namespace + ":vc-vcluster-") + ")",
            claim_expression="(request.operation == 'DELETE' ? oldObject.metadata.name : object.metadata.name) == " + json.dumps(pvc_name),
        ))
        emit(_resource_name("volume", namespace, name, "claim-policy-binding"), _render_template(
            req, "vcluster/storage-policy-binding", namespace=namespace, policy_name=policy_name,
        ))
        response.require_resources(rsp, name=key, api_version="v1", kind="PersistentVolumeClaim",
                                   namespace=namespace, match_name=pvc_name)
        observed = request.get_required_resource(req, key) or {}
        uid = observed.get("metadata", {}).get("uid")
        reference = {"name": name, "pvcRef": {"name": pvc_name, "namespace": namespace},
                     "phase": observed.get("status", {}).get("phase") or "Pending"}

        if volume.get("backups") is True:
            backup_name = "volume-snapshot-" + name
            resources = _render_template(
                req, "volumes/backup", target=namespace, pvc_name=pvc_name, volume_name=name,
                backup_name=backup_name, snapshot_class=snapshot_class, max_snapshots=str(int(max_snapshots)),
                backup_binding=_resource_name(namespace, backup_name),
                schedule=config.get("schedule") or "0 1 * * *", backup_script=BACKUP_SCRIPT,
                backup_image=(env.get("images") or {}).get("volumeSnapshot") or "python:3.13-alpine@sha256:9ef1a599f863231c3d91e941389bfdc4a2d6070557243d54df1a4e57015b960e",
            )["resources"]
            for suffix, manifest in resources.items():
                emit(_resource_name("volume", namespace, name, "backup", suffix), manifest)

        backup = {"readySnapshots": 0}
        if uid and (needs_snapshots or config.get("snapshotClassName")):
            snapshot_key = key + "-snapshots"
            response.require_resources(
                rsp, name=snapshot_key, api_version="snapshot.storage.k8s.io/v1", kind="VolumeSnapshot",
                namespace=namespace,
                match_labels={"datalabs.versioneer.at/volume": name, "datalabs.versioneer.at/source-pvc-uid": uid},
            )
            ready = [item for item in request.get_required_resources(req, snapshot_key)
                     if item.get("metadata", {}).get("namespace") == namespace
                     and item["metadata"].get("labels", {}).get("datalabs.versioneer.at/volume") == name
                     and item["metadata"]["labels"].get("datalabs.versioneer.at/source-pvc-uid") == uid
                     and not item["metadata"].get("deletionTimestamp")
                     and item.get("spec", {}).get("source", {}).get("persistentVolumeClaimName") == pvc_name
                     and item.get("status", {}).get("readyToUse") is True]
            backup["readySnapshots"] = len(ready)
            timestamps = [item["status"].get("creationTime") or item["metadata"].get("creationTimestamp") for item in ready]
            if any(timestamps):
                backup["lastSuccessfulTime"] = max(value for value in timestamps if value)
        reference["backup"] = backup
        references.append(reference)
    status["volumes"] = references
    rsp.desired.composite.resource.update({"status": status})
