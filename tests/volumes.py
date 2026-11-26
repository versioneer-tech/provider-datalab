# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Check host volume provisioning, backup status, and independent lifecycles."""

from copy import deepcopy
from helpers import load_helpers
from render import arguments, environment, manifest, render

resource_name = load_helpers("_resource_name")["_resource_name"]


def key(name, *suffix):
    return resource_name("volume", "test-volumes", name, *suffix)


def main():
    args = arguments()
    env = environment()
    env["data"]["volumes"] = {"storage": "2Gi", "storageClasses": {"allowed": ["workspace-storage"]},
                              "snapshotClassName": "workspace-snapshots"}
    env["data"].update({"packageR": {"enabled": False}, "registry": {"enabled": False}})
    source = {"apiVersion": "versioneer.at/v1", "kind": "Datalab",
              "metadata": {"name": "test-volumes", "namespace": "workspace"},
              "spec": {"users": [], "volumes": {"analysis": {"backups": True}}}}
    resources = render(args, env, source, [], include_composite=True)
    pvc = manifest(resources, key("analysis"))
    assert pvc["metadata"] == {"name": "volume-analysis", "namespace": "test-volumes",
                               "labels": {"datalabs.versioneer.at/volume": "analysis"}}
    assert pvc["spec"]["resources"]["requests"]["storage"] == "2Gi"
    assert pvc["spec"]["storageClassName"] == "workspace-storage"
    assert resources[key("analysis")]["spec"]["providerConfigRef"]["name"] == "provider-kubernetes"
    assert resources["composite"]["status"]["volumes"] == [{
        "name": "analysis", "pvcRef": {"namespace": "test-volumes", "name": "volume-analysis"}, "phase": "Pending",
        "backup": {"readySnapshots": 0},
    }]
    assert manifest(resources, key("analysis", "backup", "cronjob"))["spec"]["schedule"] == "0 1 * * *"
    fallback = deepcopy(env)
    fallback["data"]["volumes"].pop("storage")
    minimal = render(args, fallback, source, [])
    assert manifest(minimal, key("analysis"))["spec"]["resources"]["requests"]["storage"] == "1Gi"
    print("PASS named host PVCs need no virtual cluster and use the platform size and allowed StorageClass")

    source["spec"]["volumes"]["analysis"] = {"storage": "3Gi", "backups": True}
    source["spec"]["volumes"]["recovered"] = {"storage": "3Gi", "backups": True, "restoreFrom": "saved-analysis"}
    resources = render(args, env, source, [], include_composite=True)
    pvc = manifest(resources, key("analysis"))
    assert pvc["spec"]["storageClassName"] == "workspace-storage"
    assert pvc["spec"]["resources"]["requests"]["storage"] == "3Gi"
    assert "dataSource" not in pvc["spec"]
    assert manifest(resources, key("recovered"))["spec"]["dataSource"] == {
        "apiGroup": "snapshot.storage.k8s.io", "kind": "VolumeSnapshot", "name": "saved-analysis",
    }
    assert manifest(resources, key("recovered", "backup", "cronjob"))["spec"]["schedule"] == "0 1 * * *"
    job = manifest(resources, key("analysis", "backup", "cronjob"))
    pod = job["spec"]["jobTemplate"]["spec"]["template"]["spec"]
    assert pod["containers"][0]["args"] == ["test-volumes", "analysis", "volume-analysis", "workspace-snapshots", "2"]
    assert not any("persistentVolumeClaim" in volume or "secret" in volume for volume in pod["volumes"])
    role = manifest(resources, key("analysis", "backup", "role"))
    assert role["rules"][0] == {"apiGroups": [""], "resources": ["persistentvolumeclaims"],
                                "resourceNames": ["volume-analysis"], "verbs": ["get"]}
    assert not any(item.get("spec", {}).get("forProvider", {}).get("manifest", {}).get("kind") == "VolumeSnapshot"
                   for item in resources.values())
    override = deepcopy(env)
    override["data"]["volumes"]["maxSnapshots"] = 5
    override["data"]["volumes"]["schedule"] = "0 */6 * * *"
    changed = render(args, override, source, [])
    assert manifest(changed, key("analysis", "backup", "cronjob"))["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]["args"][-1] == "5"
    assert manifest(changed, key("analysis", "backup", "cronjob"))["spec"]["schedule"] == "0 */6 * * *"
    print("PASS enabled host volumes get scheduled backups with a default limit of two snapshots")

    sleeping = deepcopy(source)
    sleeping["spec"]["vclusters"] = {"vc0": {"hibernated": True}}
    independent = render(args, env, sleeping, [])
    assert manifest(independent, key("analysis", "backup", "cronjob")) == job
    assert independent[key("analysis", "backup", "cronjob")]["metadata"].get("annotations", {}).get("crossplane.io/paused") != "true"
    print("PASS host backup schedules continue when a virtual cluster is hibernated")

    native_pvc = {**pvc, "metadata": {**pvc["metadata"], "uid": "test-current-pvc"}, "status": {"phase": "Bound"}}

    def snapshot(name, ready=True, uid="test-current-pvc", deleting=False):
        value = {"apiVersion": "snapshot.storage.k8s.io/v1", "kind": "VolumeSnapshot",
                 "metadata": {"name": name, "namespace": "test-volumes",
                              "creationTimestamp": "2026-11-21T01:00:00Z",
                              "labels": {"datalabs.versioneer.at/volume": "analysis",
                                         "datalabs.versioneer.at/source-pvc-uid": uid}},
                 "spec": {"source": {"persistentVolumeClaimName": "volume-analysis"}},
                 "status": {"readyToUse": ready, "creationTime": "2026-11-21T01:00:00Z"}}
        if deleting:
            value["metadata"]["deletionTimestamp"] = "2026-11-21T02:00:00Z"
        return value

    snapshots = [snapshot("ready"), snapshot("pending", False), snapshot("old-pvc", uid="test-replaced-pvc"),
                 snapshot("deleting", deleting=True)]
    current = render(args, [env, native_pvc, *snapshots], source, [], include_composite=True)
    entry = current["composite"]["status"]["volumes"][0]
    assert entry["phase"] == "Bound"
    assert entry["backup"] == {"readySnapshots": 1, "lastSuccessfulTime": "2026-11-21T01:00:00Z"}
    replaced = deepcopy(native_pvc)
    replaced["metadata"]["uid"] = "test-new-pvc"
    source["status"] = current["composite"]["status"]
    no_backups = render(args, [env, replaced, *snapshots], source, [], include_composite=True)
    assert no_backups["composite"]["status"]["volumes"][0]["backup"] == {"readySnapshots": 0}
    print("PASS status counts only usable snapshots of the current PVC and resets after PVC replacement")

    for value in (0, 101, True, 1.5, "2"):
        invalid = deepcopy(env)
        invalid["data"]["volumes"]["maxSnapshots"] = value
        render(args, invalid, source, [], error="maxSnapshots must be an integer")
    invalid = deepcopy(env)
    invalid["data"]["volumes"].pop("snapshotClassName")
    render(args, invalid, source, [], error="require data.volumes.snapshotClassName")
    for classes in ({}, {"allowed": []}, {"allowed": ["workspace-storage", "workspace-storage"]},
                    {"allowed": ["workspace-storage"], "default": "unapproved-storage"}):
        invalid = deepcopy(env)
        invalid["data"]["volumes"]["storageClasses"] = classes
        render(args, invalid, source, [], error="data.volumes.storageClasses")
    disabled = deepcopy(source)
    disabled["spec"]["volumes"] = {"analysis": {"storage": "3Gi"}}
    retained = render(args, [env, native_pvc, *snapshots], disabled, [], include_composite=True)
    assert retained["composite"]["status"]["volumes"][0]["backup"]["readySnapshots"] == 1
    assert key("analysis", "backup", "cronjob") not in retained
    plain = deepcopy(env)
    plain["data"]["volumes"].pop("snapshotClassName")
    no_schedule = render(args, plain, disabled, [], include_composite=True)
    assert key("analysis") in no_schedule
    assert not any("backup" in name or "snapshot-class" in name for name in no_schedule)
    print("PASS backups default to disabled and do not require a snapshot class")
    removed = deepcopy(source)
    removed["spec"]["volumes"] = {}
    empty = render(args, env, removed, [], include_composite=True)
    assert not any(name.startswith("volume-") for name in empty)
    assert empty["composite"]["status"]["volumes"] == []
    print("PASS invalid backup settings and unapproved default classes fail; volume removal clears resources and status")


if __name__ == "__main__":
    main()
