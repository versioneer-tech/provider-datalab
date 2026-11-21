# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

from crossplane.function import response
from composition.helpers import _resource_name, _to_dict
from composition.render import _render_template

BACKUP_SCRIPT = _embedded_script("scripts/volume-snapshot.py")


def compose(req, rsp):
    xr = _to_dict(req.observed.composite.resource)
    spec = xr.get("spec") or {}
    volumes = spec.get("volumes") or {}
    env = _to_dict(req.context).get("apiextensions.crossplane.io/environment") or {}
    config = env.get("volumeSnapshots") or {}
    status = _to_dict(rsp.desired.composite.resource).get("status") or {}
    references = []
    for name, volume in sorted(volumes.items()):
        instance = volume["vcluster"]
        if instance not in (spec.get("vclusters") or {}):
            response.fatal(rsp, "Each volume must select a declared virtual cluster.")
            return
        target = volume.get("namespace", "default")
        pvc_name = "volume-" + name
        virtual_provider = _resource_name(xr["metadata"]["name"], "vcluster", instance)

        def virtual(suffix, manifest):
            key = _resource_name("vcluster", xr["metadata"]["name"], instance, "access", "volumes", name, suffix)
            body = _render_template(
                req, "vcluster/body", key=key,
                claim_namespace=xr["metadata"].get("namespace") or "default",
                virtual_provider=virtual_provider, manifest=manifest,
            )
            body["metadata"]["labels"] = {"datalabs.versioneer.at/vcluster": instance}
            rsp.desired.resources[key].resource.update(body)

        storage_config = (env.get("vcluster") or {}).get("storageClasses") or {}
        classes = storage_config.get("allowed") or []
        if not classes:
            response.fatal(rsp, "Volumes require allowed virtual cluster StorageClasses.")
            return
        pvc = _render_template(
            req, "volumes/pvc", target=target, pvc_name=pvc_name, volume_name=name,
            storage=volume.get("storage") or (env.get("defaults") or {}).get("volumes", {}).get("storage") or "1Gi",
            storage_class=storage_config.get("default") or classes[0],
        )
        if volume.get("restoreFrom"):
            pvc["spec"]["dataSource"] = {
                "apiGroup": "snapshot.storage.k8s.io", "kind": "VolumeSnapshot", "name": volume["restoreFrom"],
            }
        virtual("pvc", pvc)
        reference = {"name": name, "vcluster": instance, "namespace": target, "pvcName": pvc_name}
        if volume.get("backup") or volume.get("restoreFrom"):
            if (env.get("vcluster") or {}).get("volumeSnapshots") is not True:
                response.fatal(rsp, "Volume backup and restore require data.vcluster.volumeSnapshots=true.")
                return
        if volume.get("backup"):
            snapshot_class = config.get("snapshotClassName")
            if not isinstance(snapshot_class, str) or not snapshot_class.strip():
                response.fatal(rsp, "Volume backup requires data.volumeSnapshots.snapshotClassName.")
                return
            observer_key = _resource_name("volumes", xr["metadata"]["name"], instance, "snapshot-class")
            observer = _render_template(
                req, "common/object", key=observer_key,
                xr_namespace=xr["metadata"].get("namespace") or "default",
                manifest={"apiVersion": "snapshot.storage.k8s.io/v1", "kind": "VolumeSnapshotClass",
                          "metadata": {"name": snapshot_class}},
                readiness={"policy": "DeriveFromCelQuery", "celQuery": "object.deletionPolicy == 'Delete'"},
            )
            observer["spec"]["managementPolicies"] = ["Observe"]
            rsp.desired.resources[observer_key].resource.update(observer)
            retention = config.get("retention", 4)
            if (isinstance(retention, bool) or not isinstance(retention, (int, float))
                    or not 1 <= retention <= 100 or retention != int(retention)):
                response.fatal(rsp, "Snapshot retention must be an integer from 1 to 100.")
                return
            backup_name = "volume-snapshot-" + name
            resources = _render_template(
                req, "volumes/backup", target=target, pvc_name=pvc_name, volume_name=name,
                backup_name=backup_name, snapshot_class=snapshot_class, retention=str(int(retention)),
                backup_role=_resource_name("volume-snapshot", target, name),
                schedule=config.get("schedule") or "0 1 * * *", backup_script=BACKUP_SCRIPT,
                backup_image=(env.get("images") or {}).get("volumeSnapshot") or "python:3.13-alpine",
            )["resources"]
            for suffix, manifest in resources.items():
                virtual("backup-" + suffix, manifest)
            reference["backupCronJobName"] = backup_name
        references.append(reference)
    status["volumes"] = references
    rsp.desired.composite.resource.update({"status": status})
