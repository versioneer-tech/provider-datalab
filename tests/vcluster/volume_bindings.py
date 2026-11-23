# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Check a host volume through the virtual Kubernetes API."""

import time
from pathlib import Path


def check_volume_binding(api, bearer, phase):
    claim_path = "/api/v1/namespaces/demo/persistentvolumeclaims/demo"
    pod_path = "/api/v1/namespaces/demo/pods/test-bound-volume"

    def wait(check, message, seconds=300):
        deadline = time.monotonic() + seconds
        while not check():
            assert time.monotonic() < deadline, message
            time.sleep(3)

    def remove_pod():
        api(pod_path, bearer, method="DELETE", expected=(200, 202, 404))
        wait(lambda: api(pod_path, bearer, expected=(200, 404)).get("kind") != "Pod",
             "The bound volume probe did not terminate")

    if phase == "absent":
        remove_pod()
        wait(lambda: api(claim_path, bearer, expected=(200, 404)).get("kind") != "PersistentVolumeClaim",
             "The removed binding kept its virtual PVC")
        pv_path = "/api/v1/persistentvolumes/" + Path("/tmp/vcluster-bound-pv").read_text()
        wait(lambda: api(pv_path, bearer, expected=(200, 404)).get("kind") != "PersistentVolume",
             "The removed binding kept its virtual PV")
        print("PASS removing the binding removes its virtual PVC and PV", flush=True)
        return

    wait(lambda: api(claim_path, bearer, expected=(200, 404)).get("status", {}).get("phase") == "Bound",
         "The host volume binding did not become Bound")
    claim = api(claim_path, bearer)
    Path("/tmp/vcluster-bound-pv").write_text(claim["spec"]["volumeName"])
    if phase == "recreate-claim":
        remove_pod()
        for patch in ({"metadata": {"labels": {"vcluster.loft.sh/controlled-by": None}}},
                      {"metadata": {"ownerReferences": []}},
                      {"spec": {"volumeName": "another-volume"}}):
            api(claim_path, bearer, patch, method="PATCH", expected=(403, 422))
        old_uid = claim["metadata"]["uid"]
        api(claim_path, bearer, method="DELETE", expected=(200, 202))

        def recreated():
            replacement = api(claim_path, bearer, expected=(200, 404))
            return (replacement.get("metadata", {}).get("uid") not in (None, old_uid)
                    and replacement.get("status", {}).get("phase") == "Bound")

        wait(recreated, "The deleted virtual claim did not rebind with a new UID")
        print("PASS virtual PVC replacement rebinds; binding changes are denied", flush=True)

    remove_pod()
    read_only = phase != "write"
    command = ("printf 'bound-volume-data' > /data/marker; cat /data/marker"
               if not read_only else "cat /data/marker")
    if phase == "check":
        command += "; sleep 3600"
    api("/api/v1/namespaces/demo/pods", bearer, method="POST", expected=201, body={
        "apiVersion": "v1", "kind": "Pod", "metadata": {"name": "test-bound-volume"},
        "spec": {"restartPolicy": "Never", "automountServiceAccountToken": False,
                 "terminationGracePeriodSeconds": 0,
                 "securityContext": {"runAsNonRoot": True, "runAsUser": 1000, "runAsGroup": 1000,
                                     "fsGroup": 1000, "seccompProfile": {"type": "RuntimeDefault"}},
                 "containers": [{"name": "probe", "image": "busybox:1.36.1",
                                 "command": ["sh", "-ec", command],
                                 "resources": {"requests": {"cpu": "10m", "memory": "16Mi", "ephemeral-storage": "1Mi"},
                                               "limits": {"cpu": "100m", "memory": "64Mi", "ephemeral-storage": "32Mi"}},
                                 "securityContext": {"allowPrivilegeEscalation": False, "capabilities": {"drop": ["ALL"]}},
                                 "volumeMounts": [{"name": "data", "mountPath": "/data", "readOnly": read_only},
                                                  {"name": "scratch", "mountPath": "/scratch"}]}],
                 "volumes": [{"name": "data", "persistentVolumeClaim": {"claimName": "demo", "readOnly": read_only}},
                             {"name": "scratch", "emptyDir": {}}]},
    })

    def finished():
        pod = api(pod_path, bearer)
        status = pod.get("status", {})
        assert status.get("phase") != "Failed", "The bound volume probe failed: " + str(status)
        return status.get("phase") == ("Running" if phase == "check" else "Succeeded")

    wait(finished, "The bound volume probe did not finish", seconds=600)
    assert api(pod_path + "/log", bearer, raw=True).strip() == "bound-volume-data"
    print("PASS host volume data is accessible through the virtual PVC", flush=True)
