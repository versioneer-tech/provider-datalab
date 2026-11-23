# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Check snapshot retention, failure handling, and access."""

import runpy
import subprocess
import unittest
from contextlib import redirect_stdout
from io import StringIO

import yaml

from helpers import ROOT


class SnapshotBackupTests(unittest.TestCase):
    def run_backup(self, *, phase="Bound", ready=True, error=False, policy="Delete",
                   incomplete=False, cleanup_pending=False, source_replaced=False, attempts=1):
        module = runpy.run_path(str(ROOT / "scripts/volume-snapshot.py"))
        label, source = module["LABEL"], module["SOURCE"]
        calls = []
        source_reads = 0

        def snapshot(name, uid="pvc-current", volume="analysis", completed=True):
            return {"metadata": {"name": name, "uid": name + "-uid",
                                 "creationTimestamp": name,
                                 "labels": {label: volume, source: uid}},
                    "spec": {"source": {"persistentVolumeClaimName": "volume-analysis"}},
                    "status": {"readyToUse": completed}}

        snapshots = {item["metadata"]["name"]: item for item in (
            snapshot("20261120"), snapshot("20261121"),
            snapshot("old-volume", uid="pvc-replaced"), snapshot("other-volume", volume="another"),
        )}
        if incomplete:
            snapshots["incomplete"] = snapshot("incomplete", completed=False)

        class API:
            def call(self, method, path, body=None):
                nonlocal source_reads
                calls.append((method, path, body))
                if "/volumesnapshotclasses/" in path:
                    return {"deletionPolicy": policy}
                if "/persistentvolumeclaims/" in path:
                    source_reads += 1
                    uid = "pvc-replacement" if source_replaced and source_reads > 1 else "pvc-current"
                    return {"metadata": {"uid": uid}, "status": {"phase": phase}}
                if method == "POST":
                    name = "20261122-" + str(sum(method == "POST" for method, _, _ in calls))
                    item = snapshot(name, completed=ready)
                    if error:
                        item["status"]["error"] = {"message": "failed"}
                    snapshots[name] = item
                    return item
                if method == "DELETE":
                    name = path.rsplit("/", 1)[-1]
                    self_uid = snapshots[name]["metadata"]["uid"]
                    assert body["preconditions"]["uid"] == self_uid
                    if cleanup_pending:
                        snapshots[name]["metadata"]["deletionTimestamp"] = "2026-11-22T00:00:00Z"
                    else:
                        del snapshots[name]
                    return {}
                if "?" in path:
                    return {"items": list(snapshots.values())}
                return snapshots[path.rsplit("/", 1)[-1]]

        failure = None
        with redirect_stdout(StringIO()):
            for _ in range(attempts):
                try:
                    module["backup"](API(), "demo", "analysis", "volume-analysis", "snapshots", 1, timeout=0)
                except RuntimeError as error_result:
                    failure = error_result
        return calls, failure, snapshots

    def test_retention_keeps_other_volumes_and_replaced_pvcs(self):
        calls, failure, snapshots = self.run_backup()
        self.assertIsNone(failure)
        created = next(body for method, _, body in calls if method == "POST")
        self.assertEqual(created["spec"]["source"]["persistentVolumeClaimName"], "volume-analysis")
        self.assertEqual(set(snapshots), {"20261122-1", "old-volume", "other-volume"})

    def test_snapshot_failure_or_timeout_preserves_completed_backups(self):
        for options in ({"ready": False}, {"error": True}):
            with self.subTest(options=options):
                calls, failure, _ = self.run_backup(**options)
                self.assertIsInstance(failure, RuntimeError)
                self.assertFalse(any(method == "DELETE" for method, _, _ in calls))

    def test_source_replacement_during_backup_preserves_recovery_points(self):
        calls, failure, snapshots = self.run_backup(source_replaced=True)
        self.assertIn("source PVC changed", str(failure))
        self.assertTrue(any(method == "POST" for method, _, _ in calls))
        self.assertFalse(any(method == "DELETE" for method, _, _ in calls))
        self.assertIn("20261120", snapshots)
        self.assertIn("20261121", snapshots)

    def test_unbound_source_does_not_create_a_backup(self):
        calls, failure, _ = self.run_backup(phase="Pending")
        self.assertIsInstance(failure, RuntimeError)
        self.assertFalse(any(method == "POST" for method, _, _ in calls))

    def test_backup_requires_a_delete_policy(self):
        calls, failure, _ = self.run_backup(policy="Retain")
        self.assertIsInstance(failure, RuntimeError)
        self.assertFalse(any(method in ("POST", "DELETE") for method, _, _ in calls))

    def test_retries_preserve_backups_and_bound_incomplete_attempts(self):
        for options in ({"ready": False}, {"ready": False, "error": True}):
            with self.subTest(options=options):
                calls, failure, snapshots = self.run_backup(attempts=3, **options)
                self.assertIsInstance(failure, RuntimeError)
                self.assertEqual(sum(method == "POST" for method, _, _ in calls), 3)
                self.assertEqual(set(snapshots), {"20261120", "20261121", "old-volume", "other-volume", "20261122-3"})

    def test_cleanup_must_finish_before_a_new_snapshot_is_created(self):
        calls, failure, snapshots = self.run_backup(incomplete=True, cleanup_pending=True, attempts=3)
        self.assertIn("Waiting for previous snapshot cleanup", str(failure))
        self.assertFalse(any(method == "POST" for method, _, _ in calls))
        self.assertIn("20261121", snapshots)
        self.assertEqual(sum(method == "DELETE" for method, _, _ in calls), 1)


class SnapshotAccessTests(unittest.TestCase):
    def test_provider_can_observe_classes_and_bind_the_snapshot_role(self):
        objects = list(yaml.safe_load_all((ROOT / "dependencies/rbac.yaml").read_text()))
        roles = {item["metadata"]["name"]: item for item in objects if item["kind"] == "ClusterRole"}
        bindings = [item for item in objects if item["kind"] == "ClusterRoleBinding"
                    and {"kind": "ServiceAccount", "name": "provider-kubernetes", "namespace": "crossplane"}
                    in item.get("subjects", [])]
        rules = [rule for binding in bindings for rule in roles[binding["roleRef"]["name"]]["rules"]]

        def allowed(group, resource, verb, name=None):
            return any(group in rule["apiGroups"] and resource in rule["resources"]
                       and verb in rule["verbs"]
                       and ("resourceNames" not in rule or name in rule["resourceNames"]) for rule in rules)

        for verb in ("get", "list", "watch", "patch"):
            self.assertTrue(allowed("snapshot.storage.k8s.io", "volumesnapshotclasses", verb))
        for verb in ("get", "list", "watch", "create", "update", "patch", "delete"):
            self.assertTrue(allowed("rbac.authorization.k8s.io", "clusterrolebindings", verb))
        self.assertTrue(allowed("rbac.authorization.k8s.io", "clusterroles", "bind", "datalab-volume-snapshot-classes"))
        self.assertFalse(allowed("rbac.authorization.k8s.io", "clusterroles", "bind", "cluster-admin"))
        self.assertEqual(roles["datalab-volume-snapshot-classes"]["rules"], [{
            "apiGroups": ["snapshot.storage.k8s.io"], "resources": ["volumesnapshotclasses"], "verbs": ["get"],
        }])

    def test_snapshot_probe_checks_support_and_access(self):
        script = '''
set -euo pipefail
export PROVIDER_DATALAB_CLUSTER="$2"
export PROVIDER_DATALAB_STORAGE_CLASS=test-storage
export PROVIDER_DATALAB_SNAPSHOT_CLASS=test-snapshots
snapshot_driver="$3"
snapshot_policy="$4"
snapshot_apis="$5"
snapshot_access="$6"
source "$1"
kube() {
  if [[ "$1" == auth ]]; then
    if [[ "$snapshot_access" == denied || ( "$snapshot_access" == observer-denied && "$*" == *--as* ) ]]; then
      printf no; return 1
    fi
    if [[ "$*" == *--as* ]]; then
      case "$*" in
        *'volumesnapshots.snapshot.storage.k8s.io --as system:serviceaccount:crossplane:crossplane '*) ;;
        *'volumesnapshotclasses.snapshot.storage.k8s.io --as system:serviceaccount:crossplane:provider-kubernetes '*) ;;
        *) printf no; return 1 ;;
      esac
    fi
    printf yes
    return
  fi
  [[ "$1" == get ]] || { printf 'unexpected mutation'; return 1; }
  if [[ "$2" == --raw=* ]]; then
    if [[ "$snapshot_apis" == ready ]]; then
      printf '{"resources":[{"name":"volumesnapshots"},{"name":"volumesnapshotcontents"},{"name":"volumesnapshotclasses"}]}'
    else printf '{"resources":[]}'; fi
  elif [[ "$2" == storageclass/test-storage ]]; then printf 'test.csi';
  elif [[ "$2" == volumesnapshotclass/* ]]; then printf '{"driver":"%s","deletionPolicy":"%s"}' "$snapshot_driver" "$snapshot_policy";
  else printf 'unexpected mutation'; return 1; fi
}
curl() { printf 'unexpected installation'; return 1; }
check_volume_snapshot_settings && check_snapshot_observer_access verify-volumes
'''
        for mode in ("kind", "existing"):
            for driver, policy, apis, access, accepted in (
                ("test.csi", "Delete", "ready", "allowed", True), ("other.csi", "Delete", "ready", "allowed", False),
                ("test.csi", "Retain", "ready", "allowed", False), ("test.csi", "Delete", "missing", "allowed", False),
                ("test.csi", "Delete", "ready", "denied", False),
                ("test.csi", "Delete", "ready", "observer-denied", False),
            ):
                with self.subTest(mode=mode, driver=driver, policy=policy, apis=apis, access=access):
                    result = subprocess.run(["bash", "-c", script, "test", str(ROOT / "tests/integration/snapshots.bash"),
                                             mode, driver, policy, apis, access], capture_output=True, text=True)
                    self.assertEqual(result.returncode == 0, accepted, result.stderr)
                    self.assertNotIn("unexpected", result.stdout)
                    if access == "denied":
                        self.assertIn("test identity cannot read the selected VolumeSnapshotClass", result.stderr)

    def test_backup_access_rejects_missing_permissions_and_excess_access(self):
        script = '''
set -euo pipefail
source "$1"
export PROVIDER_DATALAB_SNAPSHOT_CLASS=test-snapshots
fault="$2"
sleep() { SECONDS=$((SECONDS + 120)); }
kube() {
  local request="$*"
  if [[ "$fault" == missing && "$request" == *' create volumesnapshots.'* ]]; then printf no; return 1; fi
  if [[ "$fault" == excess && "$request" == *' list secrets '* ]]; then printf yes; return; fi
  case "$request" in
    *' get persistentvolumeclaims/volume-analysis '*|*' get volumesnapshotclasses.snapshot.storage.k8s.io/test-snapshots '*) printf yes ;;
    *' volumesnapshots.snapshot.storage.k8s.io --namespace verify-volumes '*) printf yes ;;
    *) printf no; return 1 ;;
  esac
}
check_volume_backup_access verify-volumes volume-analysis volume-snapshot-analysis
'''
        for fault, message in (("none", "PASS snapshot backup permissions"),
                               ("missing", "cannot create volumesnapshots"),
                               ("excess", "must not list secrets")):
            with self.subTest(fault=fault):
                result = subprocess.run(["bash", "-c", script, "test", str(ROOT / "tests/integration/snapshots.bash"), fault],
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode == 0, fault == "none", result.stderr)
                self.assertIn(message, result.stdout + result.stderr)

    def test_missing_snapshot_support_skips_existing_targets_but_fails_kind(self):
        script = """
set -euo pipefail
source "$1"
export PROVIDER_DATALAB_CLUSTER="$2"
unset PROVIDER_DATALAB_SNAPSHOT_CLASS
if snapshot_tests_available verify-vcluster; then
  printf 'unexpected snapshot tests\\n'
fi
printf 'remaining tests\\n'
"""
        for mode in ("kind", "existing"):
            with self.subTest(mode=mode):
                result = subprocess.run(["bash", "-c", script, "test", str(ROOT / "tests/integration/snapshots.bash"), mode],
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0 if mode == "existing" else 1, result.stderr)
                self.assertNotIn("unexpected", result.stdout)
                self.assertIn("No --snapshot-class", result.stdout + result.stderr)
                if mode == "existing":
                    self.assertIn("SKIPPED: verify-vcluster snapshot tests", result.stdout)
                    self.assertIn("remaining tests", result.stdout)
                else:
                    self.assertNotIn("remaining tests", result.stdout)

    def test_kind_setup_rejects_other_targets_before_cluster_access(self):
        script = '''
export PROVIDER_DATALAB_CLUSTER="$2"
export PROVIDER_DATALAB_CONTEXT="$3"
kubectl() { printf 'unexpected Kubernetes access'; return 1; }
helm() { printf 'unexpected Helm access'; return 1; }
docker() { printf 'unexpected Docker access'; return 1; }
kind() { printf 'unexpected Kind access'; return 1; }
export -f kubectl helm docker kind
bash "$1"
'''
        for setup in ("create-cluster.bash", "kind-storage.bash"):
            for mode, context in (("existing", "test-virtual"), ("kind", "unrelated-kind")):
                with self.subTest(setup=setup, mode=mode, context=context):
                    result = subprocess.run(["bash", "-c", script, "test", str(ROOT / "tests/integration" / setup),
                                             mode, context], capture_output=True, text=True)
                    self.assertEqual(result.returncode, 2)
                    self.assertIn("only available for the dedicated Kind cluster", result.stderr)
                    self.assertNotIn("unexpected", result.stdout)


if __name__ == "__main__":
    unittest.main()
