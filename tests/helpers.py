# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

import runpy
import base64
import subprocess
import json
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
BUILDER = runpy.run_path(str(ROOT / "scripts/build-composition.py"))
inline_helpers = BUILDER["inline_helpers"]
HELPER_SOURCE = (ROOT / "composition/helpers.py").read_text()


def load_helpers(*names):
    script = f"from composition.helpers import {', '.join(names)}\n"
    namespace = {}
    # Run the embedded code without a repository module in the function runtime.
    exec(inline_helpers(script, HELPER_SOURCE), namespace)
    return namespace


class HelperTests(unittest.TestCase):
    def test_build_rejects_duplicate_pipeline_steps(self):
        with TemporaryDirectory(prefix="test-pipeline-") as directory:
            root = Path(directory)
            (root / "composition").mkdir()
            (root / "composition/settings.yaml").write_text("responseTTL: 5m\n")
            (root / "composition/pipeline.yaml").write_text(
                "spec:\n  pipeline:\n  - step: registry\n  - step: registry\n"
            )
            with self.assertRaisesRegex(ValueError, "step names must be unique"):
                BUILDER["build"](root)

    def test_backup_size_controls_enablement(self):
        enabled = load_helpers("_backup_enabled")["_backup_enabled"]
        for size in (None, "", "0", "0Gi", "0.0Gi", "0.0G", "0e3"):
            with self.subTest(size=size):
                self.assertFalse(enabled(size))
        for size in ("1Gi", "0.5Gi", ".5G", "1e3", "1e-3", "+1Mi", "1m"):
            with self.subTest(size=size):
                self.assertTrue(enabled(size))
        for size in ("-1Gi", "invalid", "1GB"):
            with self.subTest(size=size):
                with self.assertRaisesRegex(ValueError, "backupStorage"):
                    enabled(size)

    def test_service_tokens_do_not_change(self):
        token = load_helpers("_strong_token")["_strong_token"]
        self.assertEqual(token("sample:mongo"), "4YlC2SJsBu45oGi9FbJZFBypWCpXR-vU")
        self.assertEqual(
            token("sample:redis", suffix="", length=28), "E6xDTnRLBJ1XV75rV3xJDiEsGpHp"
        )


class VolumeSnapshotTests(unittest.TestCase):
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

    def test_completed_backup_prunes_only_older_completed_snapshots_of_this_pvc(self):
        calls, failure, snapshots = self.run_backup()
        self.assertIsNone(failure)
        created = next(body for method, _, body in calls if method == "POST")
        self.assertEqual(created["spec"]["source"]["persistentVolumeClaimName"], "volume-analysis")
        self.assertNotIn("ownerReferences", created["metadata"])
        removed = [(path.rsplit("/", 1)[-1], body["preconditions"])
                   for method, path, body in calls if method == "DELETE"]
        self.assertEqual(removed, [("20261121", {"uid": "20261121-uid"}),
                                   ("20261120", {"uid": "20261120-uid"})])
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

    def test_retained_snapshot_class_does_not_start_an_unbounded_backup(self):
        calls, failure, _ = self.run_backup(policy="Retain")
        self.assertIsInstance(failure, RuntimeError)
        self.assertFalse(any(method in ("POST", "DELETE") for method, _, _ in calls))

    def test_repeated_failures_keep_one_incomplete_attempt_and_all_recovery_points(self):
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

    def test_provider_can_observe_the_class_and_bind_the_operator_owned_snapshot_role(self):
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

    def test_snapshot_settings_are_checked_without_installation_for_every_target(self):
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
    if [[ "$snapshot_access" == allowed ]]; then printf yes; else printf no; return 1; fi
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
check_volume_snapshot_settings
'''
        for mode in ("kind", "existing"):
            for driver, policy, apis, access, accepted in (
                ("test.csi", "Delete", "ready", "allowed", True), ("other.csi", "Delete", "ready", "allowed", False),
                ("test.csi", "Retain", "ready", "allowed", False), ("test.csi", "Delete", "missing", "allowed", False),
                ("test.csi", "Delete", "ready", "denied", False),
            ):
                with self.subTest(mode=mode, driver=driver, policy=policy, apis=apis, access=access):
                    result = subprocess.run(["bash", "-c", script, "test", str(ROOT / "tests/integration/snapshots.bash"),
                                             mode, driver, policy, apis, access], capture_output=True, text=True)
                    self.assertEqual(result.returncode == 0, accepted, result.stderr)
                    self.assertNotIn("unexpected", result.stdout)
                    if access == "denied":
                        self.assertIn("test identity cannot create VolumeSnapshots", result.stderr)

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

    def test_existing_volume_runner_requires_a_snapshot_class_before_cluster_access(self):
        script = '''
unset PROVIDER_DATALAB_SNAPSHOT_CLASS
kubectl() { printf 'unexpected Kubernetes access'; return 1; }
kind() { printf 'unexpected Kind access'; return 1; }
docker() { printf 'unexpected Docker access'; return 1; }
export -f kubectl kind docker
runner="$1"
shift
bash "$runner" "$@"
'''
        for profile in ("all", "verify-volumes", "verify-vcluster"):
            with self.subTest(profile=profile):
                result = subprocess.run(["bash", "-c", script, "test", str(ROOT / "tests/integration/run.bash"),
                                         profile, "--kubeconfig", "/test/selected.kubeconfig", "--context", "test-virtual"],
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 2)
                self.assertIn("needs --snapshot-class", result.stderr)
                self.assertNotIn("unexpected", result.stdout)

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


class VclusterCleanupTests(unittest.TestCase):
    def setUp(self):
        self.cleanup = runpy.run_path(str(ROOT / "scripts/vcluster-cleanup.py"))["cleanup_once"]
        self.sts = {"metadata": {"uid": "control-uid", "generation": 1, "annotations": {
            "datalabs.versioneer.at/lifecycle-request": json.dumps({"generation": 2, "hibernated": True})}},
            "spec": {"replicas": 0}}
        self.pods = []
        self.deleted = []

    def call(self, method, path, body=None):
        self.assertIn("/namespaces/test-team/", path)
        if method == "DELETE":
            self.assertIn("/pods/", path)
            self.deleted.append((path.rsplit("/", 1)[1], body["preconditions"]["uid"]))
            return {}
        if "/statefulsets/" in path:
            return json.loads(json.dumps(self.sts))
        if "/services/" in path:
            return {"metadata": {"uid": "service-uid"}}
        self.assertTrue(path.endswith("/pods"))
        return {"items": self.pods}

    def pod(self, name, kind="Service", owner="service-uid", phase="Running"):
        return {"metadata": {"name": name, "uid": name + "-uid", "ownerReferences": [
            {"kind": kind, "uid": owner}], "labels": {"vcluster.loft.sh/managed-by": "vcluster-vc0"}},
                "status": {"phase": phase}}

    def test_cleanup_waits_for_control_plane_and_keeps_other_instances(self):
        self.pods = [self.pod("control", "StatefulSet", "control-uid"), self.pod("worker")]
        self.assertFalse(self.cleanup(self, "test-team", "vcluster-vc0", 2))
        self.assertEqual(self.deleted, [])
        self.pods = [self.pod("worker"), self.pod("pending", phase="Pending"),
                     self.pod("coredns"), self.pod("application-controller"),
                     self.pod("other-instance", owner="other-service"),
                     {"metadata": {"name": "shared-host-service"}}]
        self.assertFalse(self.cleanup(self, "test-team", "vcluster-vc0", 2))
        self.assertEqual(self.deleted, [(name, name + "-uid") for name in
                                       ("worker", "pending", "coredns", "application-controller")])

    def test_cleanup_is_repeatable_and_never_deletes_storage(self):
        self.pods = [self.pod("worker")]
        self.assertFalse(self.cleanup(self, "test-team", "vcluster-vc0", 2))
        self.pods[0]["metadata"]["deletionTimestamp"] = "2026-11-20T00:00:00Z"
        self.assertFalse(self.cleanup(self, "test-team", "vcluster-vc0", 2))
        self.assertEqual(len(self.deleted), 1)
        self.pods = []
        self.assertTrue(self.cleanup(self, "test-team", "vcluster-vc0", 2))
        self.assertTrue(self.cleanup(self, "test-team", "vcluster-vc0", 2))

    def test_cleanup_does_not_run_against_a_resumed_control_plane(self):
        self.sts["spec"]["replicas"] = 1
        self.pods = [self.pod("resumed-worker")]
        self.assertFalse(self.cleanup(self, "test-team", "vcluster-vc0", 2))
        self.assertEqual(self.deleted, [])

    def test_resume_during_pod_list_invalidates_cleanup(self):
        original = self.call

        def resume(method, path, body=None):
            result = original(method, path, body)
            if path.endswith('/pods'):
                self.sts['metadata']['generation'] += 1
                self.sts['spec']['replicas'] = 1
            return result

        self.call = resume
        self.pods = [self.pod('resumed-worker')]
        self.assertFalse(self.cleanup(self, 'test-team', 'vcluster-vc0', 2))
        self.assertEqual(self.deleted, [])
        self.sts['metadata']['annotations']['datalabs.versioneer.at/lifecycle-request'] = json.dumps(
            {'generation': 3, 'hibernated': False})
        with self.assertRaisesRegex(RuntimeError, 'superseded'):
            self.cleanup(self, 'test-team', 'vcluster-vc0', 2)


class VclusterCredentialTests(unittest.TestCase):
    def setUp(self):
        self.now = 1900000000
        self.requests = []
        self.sleeps = []
        self.prompts = []

    def access_token(self, exp=None):
        payload = base64.urlsafe_b64encode(json.dumps({"exp": exp or self.now + 300}).encode()).decode().rstrip("=")
        return "header." + payload + ".signature"

    def response(self, *values):
        from urllib.error import HTTPError
        from urllib.parse import parse_qs
        responses = iter(values)

        def request(request, **kwargs):
            self.requests.append((request.full_url, parse_qs(request.data.decode())))
            value = next(responses)
            if "error" in value:
                raise HTTPError(request.full_url, 400, "Bad request", {}, StringIO(json.dumps(value)))
            return StringIO(json.dumps(value))
        return request

    def device(self, **values):
        return {"device_code": "test-device", "user_code": "TEST-CODE", "expires_in": 60,
                "interval": 1, "verification_uri": "https://identity.example/device", **values}

    def run_helper(self, files, response=None, args=(), interactive=False, prompt=None):
        module = runpy.run_path(str(ROOT / "scripts/vcluster-credentials.py"))
        output, error = StringIO(), StringIO()
        argv = ["credentials.py", "--issuer", "https://identity.example/realms/test", "--client-id", "s-joe", *args]

        def sleep(seconds):
            self.sleeps.append(seconds)
            self.now += seconds

        def secret_prompt(message, **kwargs):
            self.prompts.append(message)
            if prompt is None:
                raise AssertionError('Unexpected client secret prompt')
            return prompt() if callable(prompt) else prompt

        with TemporaryDirectory(prefix="test-vcluster-credentials-") as directory, \
                patch.object(sys, "argv", argv), \
                patch.object(module["os"], "environ", {"DATALAB_TOKEN_CACHE_DIR": directory, **files}), \
                patch.dict(module["main"].__globals__, {"urlopen": response, "getpass": secret_prompt}), \
                patch.object(sys.stdin, "isatty", return_value=interactive), \
                patch.object(module["time"], "time", lambda: self.now), \
                patch.object(module["time"], "monotonic", lambda: self.now), \
                patch.object(module["time"], "sleep", sleep), \
                redirect_stdout(output), redirect_stderr(error):
            try:
                code = module["main"]()
            except SystemExit as exc:
                code = exc.code
        return code, output.getvalue(), error.getvalue()

    def test_profile_requires_a_separate_credential_source(self):
        code, output, error = self.run_helper({})
        self.assertNotEqual(code, 0)
        self.assertEqual(output, "")
        self.assertIn("DATALAB_ACCESS_TOKEN_FILE", error)

    def test_human_token_is_used_without_an_identity_exchange(self):
        with TemporaryDirectory(prefix="test-vcluster-access-token-") as directory:
            token = Path(directory) / "access-token"
            value = self.access_token()
            token.write_text(value + "\n")
            code, output, _ = self.run_helper({"DATALAB_ACCESS_TOKEN_FILE": str(token)})
        self.assertEqual(code, 0)
        status = json.loads(output)["status"]
        self.assertEqual(status["token"], value)
        self.assertIn("expirationTimestamp", status)

    def test_device_login_uses_user_authorization_and_caches_private_tokens(self):
        value = self.access_token()
        with TemporaryDirectory(prefix="test-vcluster-credentials-") as directory:
            secret = Path(directory) / "client-secret"
            secret.write_text("separate-client-secret\n")
            cache = Path(directory) / "cache"
            files = {"DATALAB_CLIENT_SECRET_FILE": str(secret), "DATALAB_TOKEN_CACHE_DIR": str(cache)}
            code, output, error = self.run_helper(files, self.response(
                self.device(), {"error": "authorization_pending"}, {"error": "slow_down"},
                {"access_token": value, "expires_in": 300, "refresh_token": "test-refresh"},
            ))
            self.assertEqual(code, 0, error)
            self.assertEqual(json.loads(output)["status"]["token"], value)
            self.assertIn("https://identity.example/device", error)
            self.assertIn("TEST-CODE", error)
            self.assertNotIn("test-refresh", output + error)
            self.assertNotIn("separate-client-secret", output + error)
            self.assertEqual(self.sleeps, [1, 1, 6])
            self.assertEqual(cache.stat().st_mode & 0o777, 0o700)
            cached = list(cache.glob("*.json"))
            self.assertEqual(len(cached), 1)
            self.assertEqual(cached[0].stat().st_mode & 0o777, 0o600)
            self.assertNotIn("separate-client-secret", cached[0].read_text())
            code, output, error = self.run_helper(files)
            self.assertEqual(code, 0, error)
            self.assertEqual(json.loads(output)["status"]["token"], value)
            self.assertEqual(error, "")
        device_url, authorization = self.requests[0]
        self.assertTrue(device_url.endswith("/auth/device"))
        self.assertEqual(authorization, {
            "client_id": ["s-joe"], "client_secret": ["separate-client-secret"],
            "scope": ["offline_access openid s-joe:interactive"],
        })
        for _, request in self.requests[1:]:
            self.assertEqual(request["grant_type"], ["urn:ietf:params:oauth:grant-type:device_code"])
            self.assertEqual(request["device_code"], ["test-device"])
            self.assertEqual(request["client_secret"], ["separate-client-secret"])

    def test_expired_access_token_refreshes_without_device_login(self):
        with TemporaryDirectory(prefix="test-vcluster-credentials-") as directory:
            files = {"DATALAB_CLIENT_SECRET_VALUE": "test-secret", "DATALAB_TOKEN_CACHE_DIR": directory}
            args = ["--client-secret-env", "DATALAB_CLIENT_SECRET_VALUE"]
            code, _, error = self.run_helper(files, self.response(self.device(), {
                "access_token": self.access_token(), "expires_in": 300, "refresh_token": "old-refresh",
            }), args)
            self.assertEqual(code, 0, error)
            self.now += 400
            value = self.access_token()
            code, output, error = self.run_helper(files, self.response({
                "access_token": value, "expires_in": 300, "refresh_token": "new-refresh",
            }), args)
            self.assertEqual(code, 0, error)
            self.assertEqual(json.loads(output)["status"]["token"], value)
            self.assertEqual(error, "")
            self.assertEqual(json.loads(next(Path(directory).glob("*.json")).read_text())["refresh_token"], "new-refresh")
        self.assertEqual(self.requests[-1][1]["grant_type"], ["refresh_token"])
        self.assertEqual(self.requests[-1][1]["refresh_token"], ["old-refresh"])

    def test_rejected_refresh_starts_new_login_and_discards_old_refresh_token(self):
        with TemporaryDirectory(prefix="test-vcluster-credentials-") as directory:
            files = {"DATALAB_CLIENT_SECRET_VALUE": "test-secret", "DATALAB_TOKEN_CACHE_DIR": directory}
            args = ["--client-secret-env", "DATALAB_CLIENT_SECRET_VALUE"]
            self.run_helper(files, self.response(self.device(), {
                "access_token": self.access_token(), "expires_in": 300, "refresh_token": "old-refresh",
            }), args)
            self.now += 400
            code, _, error = self.run_helper(files, self.response(
                {"error": "invalid_grant"}, self.device(),
                {"access_token": self.access_token(), "expires_in": 300},
            ), args)
            self.assertEqual(code, 0, error)
            self.assertIsNone(json.loads(next(Path(directory).glob("*.json")).read_text())["refresh_token"])

    def test_cli_login_refreshes_after_online_session_limits_and_ends_after_thirty_days(self):
        with TemporaryDirectory(prefix="test-vcluster-credentials-") as directory:
            files = {"DATALAB_CLIENT_SECRET_VALUE": "test-secret", "DATALAB_TOKEN_CACHE_DIR": directory}
            args = ["--client-secret-env", "DATALAB_CLIENT_SECRET_VALUE"]
            started = self.now
            code, _, error = self.run_helper(files, self.response(self.device(), {
                "access_token": self.access_token(), "expires_in": 300, "refresh_token": "offline-refresh",
            }), args)
            self.assertEqual(code, 0, error)
            self.now = started + 29 * 24 * 60 * 60
            code, _, error = self.run_helper(files, self.response({
                "access_token": self.access_token(), "expires_in": 300, "refresh_token": "rotated-offline-refresh",
            }), args)
            self.assertEqual(code, 0, error)
            self.assertEqual(error, "")
            self.assertEqual(self.requests[-1][1]["grant_type"], ["refresh_token"])
            cached = json.loads(next(Path(directory).glob("*.json")).read_text())
            self.assertEqual(cached["session_expires_at"], started + 1 + 30 * 24 * 60 * 60)
            self.now = started + 31 * 24 * 60 * 60
            code, _, error = self.run_helper(files, self.response(self.device(), {
                "access_token": self.access_token(), "expires_in": 300, "refresh_token": "new-offline-refresh",
            }), args)
            self.assertEqual(code, 0, error)
            self.assertIn("TEST-CODE", error)
            self.assertTrue(self.requests[-2][0].endswith('/auth/device'))

    def test_refresh_policy_error_does_not_start_device_login_or_change_scopes(self):
        with TemporaryDirectory(prefix="test-vcluster-credentials-") as directory:
            files = {"DATALAB_CLIENT_SECRET_VALUE": "test-secret", "DATALAB_TOKEN_CACHE_DIR": directory}
            args = ["--client-secret-env", "DATALAB_CLIENT_SECRET_VALUE"]
            self.run_helper(files, self.response(self.device(), {
                "access_token": self.access_token(), "expires_in": 300, "refresh_token": "offline-refresh",
            }), args)
            self.now += 400
            requests_before = len(self.requests)
            code, output, error = self.run_helper(files, self.response({
                "error": "invalid_request", "error_description": "Request not allowed",
            }), args)
            self.assertEqual(code, 1)
            self.assertEqual(output, "")
            self.assertIn("client policies", error)
            self.assertEqual(len(self.requests), requests_before + 1)
            self.assertEqual(self.requests[-1][1]["grant_type"], ["refresh_token"])
            self.assertNotIn("scope", self.requests[-1][1])

    def test_device_denial_expiry_and_bad_client_return_no_credentials(self):
        for responses in (
            [self.device(), {"error": "access_denied"}],
            [self.device(expires_in=3), {"error": "authorization_pending"}, {"error": "authorization_pending"}],
            [{"error": "invalid_client"}],
        ):
            with self.subTest(responses=responses), TemporaryDirectory(prefix="test-vcluster-credentials-") as directory:
                code, output, _ = self.run_helper({
                    "DATALAB_CLIENT_SECRET_VALUE": "test-secret", "DATALAB_TOKEN_CACHE_DIR": directory,
                }, self.response(*responses), ["--client-secret-env", "DATALAB_CLIENT_SECRET_VALUE"])
                self.assertNotEqual(code, 0)
                self.assertEqual(output, "")
                self.assertEqual(list(Path(directory).glob("*.json")), [])

    def test_cache_is_separate_for_issuer_client_and_scopes_and_can_force_login(self):
        with TemporaryDirectory(prefix="test-vcluster-credentials-") as directory:
            files = {"DATALAB_CLIENT_SECRET_VALUE": "test-secret", "DATALAB_TOKEN_CACHE_DIR": directory}
            for extra in ([], ["--issuer", "https://other.example/realm"], ["--client-id", "s-other"],
                          ["--scope", "s-joe:vclusters_vc0_demo"], ["--force-login"]):
                code, _, error = self.run_helper(files, self.response(self.device(), {
                    "access_token": self.access_token(), "expires_in": 300,
                }), ["--client-secret-env", "DATALAB_CLIENT_SECRET_VALUE", *extra])
                self.assertEqual(code, 0, error)
            self.assertEqual(len(list(Path(directory).glob("*.json"))), 4)
        self.assertEqual(len(self.requests), 10)

    def test_missing_secret_prompts_once_and_cached_token_needs_no_secret(self):
        with TemporaryDirectory(prefix="test-vcluster-credentials-") as directory:
            files = {"DATALAB_TOKEN_CACHE_DIR": directory,
                     "KUBERNETES_EXEC_INFO": json.dumps({"spec": {"interactive": True}})}
            value = self.access_token()
            code, output, error = self.run_helper(files, self.response(self.device(), {
                "access_token": value, "expires_in": 300, "refresh_token": "test-refresh",
            }), interactive=True, prompt="prompted-secret")
            self.assertEqual(code, 0, error)
            self.assertEqual(json.loads(output)["status"]["token"], value)
            self.assertNotIn("prompted-secret", output + error)
            self.assertNotIn("prompted-secret", next(Path(directory).glob("*.json")).read_text())
            code, output, error = self.run_helper({
                **files, "KUBERNETES_EXEC_INFO": json.dumps({"spec": {"interactive": False}}),
            })
            self.assertEqual(code, 0, error)
            self.assertEqual(json.loads(output)["status"]["token"], value)
            self.assertEqual(len(self.prompts), 1)
            self.assertEqual(self.requests[0][1]["client_secret"], ["prompted-secret"])

    def test_refresh_prompts_when_the_secret_is_not_stored(self):
        with TemporaryDirectory(prefix="test-vcluster-credentials-") as directory:
            files = {"DATALAB_TOKEN_CACHE_DIR": directory}
            code, _, error = self.run_helper(files, self.response(self.device(), {
                "access_token": self.access_token(), "expires_in": 300, "refresh_token": "test-refresh",
            }), interactive=True, prompt="prompted-secret")
            self.assertEqual(code, 0, error)
            self.now += 400
            value = self.access_token()
            code, output, error = self.run_helper(files, self.response({
                "access_token": value, "expires_in": 300,
            }), interactive=True, prompt="prompted-secret")
            self.assertEqual(code, 0, error)
            self.assertEqual(json.loads(output)["status"]["token"], value)
            self.assertEqual(len(self.prompts), 2)
            self.assertEqual(self.requests[-1][1]["grant_type"], ["refresh_token"])

    def test_exec_contract_prevents_a_secret_prompt_when_stdin_is_unavailable(self):
        for info in ({"spec": {"interactive": False}}, {"spec": {}}):
            code, output, error = self.run_helper({"KUBERNETES_EXEC_INFO": json.dumps(info)}, interactive=True)
            self.assertNotEqual(code, 0)
            self.assertEqual(output, "")
            self.assertIn("DATALAB_CLIENT_SECRET_FILE", error)
            self.assertEqual(self.prompts, [])

    def test_secret_prompt_cannot_fall_back_to_echo(self):
        from getpass import GetPassWarning
        import warnings

        def echo_warning():
            warnings.warn('Terminal control unavailable', GetPassWarning)

        code, output, _ = self.run_helper({}, interactive=True, prompt=echo_warning)
        self.assertNotEqual(code, 0)
        self.assertEqual(output, "")
        self.assertEqual(self.requests, [])

    def test_corrupt_cache_starts_device_login(self):
        with TemporaryDirectory(prefix="test-vcluster-credentials-") as directory:
            files = {"DATALAB_CLIENT_SECRET_VALUE": "test-secret", "DATALAB_TOKEN_CACHE_DIR": directory}
            args = ["--client-secret-env", "DATALAB_CLIENT_SECRET_VALUE"]
            response = lambda: self.response(self.device(), {"access_token": self.access_token(), "expires_in": 300})
            self.run_helper(files, response(), args)
            next(Path(directory).glob("*.json")).write_text("incomplete json")
            code, _, error = self.run_helper(files, response(), args)
            self.assertEqual(code, 0, error)

    def test_empty_or_ambiguous_sources_fail_without_a_credential(self):
        with TemporaryDirectory(prefix="test-vcluster-credential-sources-") as directory:
            empty = Path(directory) / "empty"
            empty.write_text("")
            for sources in (
                {"DATALAB_ACCESS_TOKEN_FILE": str(empty)},
                {"DATALAB_CLIENT_SECRET_FILE": str(empty)},
                {"DATALAB_ACCESS_TOKEN_FILE": str(empty), "DATALAB_CLIENT_SECRET_FILE": str(empty)},
            ):
                code, output, _ = self.run_helper(sources)
                self.assertNotEqual(code, 0)
                self.assertEqual(output, "")


class VclusterDelegatedTokenTests(unittest.TestCase):
    @staticmethod
    def access_token(exp=1893456000):
        payload = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode().rstrip("=")
        return "header." + payload + ".signature"

    def run_helper(self, files, args=()):
        module = runpy.run_path(str(ROOT / "scripts/vcluster-credentials.py"))
        output, error = StringIO(), StringIO()
        argv = ["credentials.py", "--token-only", *args]
        with patch.object(sys, "argv", argv), patch.object(module["os"], "environ", files), \
                redirect_stdout(output), redirect_stderr(error):
            try:
                code = module["main"]()
            except SystemExit as exc:
                code = exc.code
        return code, output.getvalue(), error.getvalue()

    def test_profile_requires_a_separate_credential_source(self):
        code, output, error = self.run_helper({})
        self.assertNotEqual(code, 0)
        self.assertEqual(output, "")
        self.assertIn("DATALAB_ACCESS_TOKEN_FILE", error)

    def test_delegated_token_sources_need_no_client_credentials(self):
        with TemporaryDirectory(prefix="test-vcluster-credentials-") as directory:
            token = Path(directory) / "access-token"
            value = self.access_token()
            token.write_text(value + "\n")
            for files, args in (
                ({"DATALAB_ACCESS_TOKEN_FILE": str(token)}, []),
                ({}, ["--access-token-file", str(token)]),
                ({"DATALAB_ACCESS_TOKEN_FILE": str(token),
                  "DATALAB_CLIENT_SECRET_FILE": "/unused/client-secret"}, []),
            ):
                with self.subTest(files=files, args=args):
                    code, output, error = self.run_helper(files, args)
                    self.assertEqual(code, 0, error)
                    self.assertEqual(json.loads(output)["status"], {
                        "token": value, "expirationTimestamp": "2030-01-01T00:00:00Z",
                    })

    def test_client_secret_cannot_replace_a_caller_token(self):
        code, output, _ = self.run_helper({"DATALAB_CLIENT_SECRET_FILE": "/unused/client-secret"})
        self.assertNotEqual(code, 0)
        self.assertEqual(output, "")

    def test_empty_or_missing_token_files_fail_without_a_credential(self):
        with TemporaryDirectory(prefix="test-vcluster-credentials-") as directory:
            empty = Path(directory) / "empty"
            empty.write_text("")
            for token in (empty, Path(directory) / "missing"):
                with self.subTest(token=token.name):
                    code, output, _ = self.run_helper({"DATALAB_ACCESS_TOKEN_FILE": str(token)})
                    self.assertNotEqual(code, 0)
                    self.assertEqual(output, "")

    def test_invalid_token_expiry_fails_without_a_credential(self):
        with TemporaryDirectory(prefix="test-vcluster-credentials-") as directory:
            token = Path(directory) / "access-token"
            for value in ("invalid", "header.e30.signature", self.access_token("invalid")):
                with self.subTest(value=value):
                    token.write_text(value)
                    code, output, _ = self.run_helper({"DATALAB_ACCESS_TOKEN_FILE": str(token)})
                    self.assertNotEqual(code, 0)
                    self.assertEqual(output, "")


class BuildAndHarnessTests(unittest.TestCase):
    def test_existing_cluster_does_not_adopt_other_namespaces(self):
        script = '''
export PROVIDER_DATALAB_CLUSTER=existing
source "$1"
kube() { printf 'crossplane '; }
check_test_namespaces
'''
        result = subprocess.run(["bash", "-c", script, "test", str(ROOT / "tests/integration/lib.bash")],
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("already exists outside this test suite", result.stderr)

    def test_network_traffic_checks_run_only_in_kind(self):
        script = '''
export PROVIDER_DATALAB_CLUSTER="$2"
export PROVIDER_DATALAB_KUBECONFIG=/test/selected.kubeconfig
export PROVIDER_DATALAB_CONTEXT=test-virtual
source "$1"
require_cluster() { :; }
require_command() { :; }
apply_verification_resources() { :; }
wait_for_verification_resources() { printf 'network probes\\n'; }
python3() { printf 'resource limit checks\\n'; }
run_network_checks() { printf 'network traffic checks\\n'; }
cleanup_successful_verification() { :; }
main
'''
        for mode in ("kind", "existing"):
            with self.subTest(mode=mode):
                result = subprocess.run(["bash", "-c", script, "test",
                                         str(ROOT / "tests/integration/verify-network.bash"), mode],
                                        capture_output=True, text=True, check=True)
                self.assertIn("resource limit checks", result.stdout)
                if mode == "kind":
                    self.assertIn("network traffic checks", result.stdout)
                    self.assertNotIn("SKIP", result.stdout)
                else:
                    self.assertNotIn("network probes", result.stdout)
                    self.assertNotIn("network traffic checks", result.stdout)
                    self.assertIn("SKIP NetworkPolicy traffic checks", result.stdout)

    def test_existing_cluster_requires_an_explicit_context(self):
        script = '''
export PROVIDER_DATALAB_CLUSTER=existing
export PROVIDER_DATALAB_KUBECONFIG=/test/selected.kubeconfig
unset PROVIDER_DATALAB_CONTEXT
source "$1"
kube() { printf 'unexpected Kubernetes call\\n'; }
require_cluster
'''
        result = subprocess.run(["bash", "-c", script, "test", str(ROOT / "tests/integration/lib.bash")],
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("explicit kubeconfig and context", result.stderr)
        self.assertNotIn("unexpected Kubernetes call", result.stdout)

    def test_existing_cluster_uses_only_the_selected_target(self):
        with TemporaryDirectory(prefix="test-cluster-target-") as directory:
            kubectl = Path(directory) / "kubectl"
            kubectl.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
            kubectl.chmod(0o755)
            script = '''
export PROVIDER_DATALAB_CLUSTER=existing
export PROVIDER_DATALAB_KUBECONFIG=/test/selected.kubeconfig
export PROVIDER_DATALAB_CONTEXT=test-virtual
source "$1"
PATH="$2:/usr/bin:/bin"
kind_cluster_exists() { printf 'unexpected Kind call\\n'; return 1; }
export_kind_kubeconfig() { printf 'unexpected kubeconfig write\\n'; return 1; }
require_cluster
kube get namespaces
'''
            result = subprocess.run(["bash", "-c", script, "test",
                                     str(ROOT / "tests/integration/lib.bash"), directory],
                                    capture_output=True, text=True, check=True)
            self.assertEqual(result.stdout.splitlines(), [
                "--kubeconfig", "/test/selected.kubeconfig", "--context", "test-virtual",
                "get", "namespaces",
            ])

    def test_existing_cluster_does_not_load_images_into_kind(self):
        script = '''
export PROVIDER_DATALAB_CLUSTER=existing
source "$1"
docker() { printf '%s\\n' "$*"; }
kind() { printf 'unexpected Kind call\\n'; return 1; }
publish_test_image registry.example.org/tests/client:test /test/empty-docker-config
'''
        result = subprocess.run(["bash", "-c", script, "test", str(ROOT / "tests/integration/lib.bash")],
                                capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.strip(), "push registry.example.org/tests/client:test")

    def test_cluster_settings_reach_every_environment(self):
        configure = runpy.run_path(str(ROOT / "tests/integration/environment.py"))["configure"]
        documents = [{"data": {"network": {"internalEgress": [{"namespace": "minio"}]}}},
                     {"data": {"vcluster": {"resources": {"limits": {"cpu": "4"}}}}}]
        result = configure(documents, "test-storage", "10.20.0.0/16", "10.30.0.0/16,10.40.0.0/16")
        for item in result:
            self.assertEqual(item["data"]["network"]["serviceCIDR"], "10.20.0.0/16")
            self.assertEqual(item["data"]["network"]["podCIDRs"], ["10.30.0.0/16", "10.40.0.0/16"])
            self.assertEqual(item["data"]["volumes"]["storageClasses"], {
                "allowed": ["test-storage"], "default": "test-storage",
            })
        self.assertEqual(result[0]["data"]["network"]["internalEgress"], [{"namespace": "minio"}])
        self.assertEqual(result[1]["data"]["vcluster"]["resources"]["limits"]["cpu"], "4")
        with self.assertRaises(ValueError):
            configure(documents, "test-storage", "invalid", "10.30.0.0/16")

    def test_registry_bucket_has_storage_credentials(self):
        manifests = ROOT / "tests/integration/manifests"
        datalab = yaml.safe_load((manifests / "registry/datalab.yaml").read_text())
        bucket = yaml.safe_load((manifests / "registry/bucket.yaml").read_text())
        secrets = {
            (item["metadata"]["namespace"], item["metadata"]["name"])
            for item in yaml.safe_load_all((manifests / "storage-secrets.yaml").read_text())
            if item["kind"] == "Secret"
        }
        secret_name = bucket["spec"]["containers"][0]["envFrom"][0]["secretRef"]["name"]
        self.assertEqual(secret_name, datalab["metadata"]["name"])
        self.assertIn((datalab["metadata"]["namespace"], secret_name), secrets)

    def test_ttl_override_cannot_replace_deployment_artifact(self):
        artifact = ROOT / "composition.yaml"
        original = artifact.read_bytes()
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts/build-composition.py"), "--response-ttl", "1m"],
            capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires a separate --output", result.stderr)
        self.assertEqual(artifact.read_bytes(), original)

    def test_operator_with_managed_resources_stays_running(self):
        script = '''
source "$1"
kube() {
  if [[ "$1" == get ]]; then printf '{"items":[{"metadata":{"name":"retained"}}]}';
  else printf 'unexpected mutation: %s\\n' "$*"; fi
}
stop_unused_operator database operator databases.example.org
'''
        result = subprocess.run(["bash", "-c", script, "test", str(ROOT / "tests/integration/lib.bash")],
                                capture_output=True, text=True, check=True)
        self.assertIn("Keeping operator running", result.stdout)
        self.assertNotIn("unexpected mutation", result.stdout)

    def test_scheduling_failure_reports_before_execution_wait(self):
        script = '''
source "$1"
kube() { [[ "$*" != *condition=PodScheduled* ]]; }
scheduling_diagnostics() { printf 'scheduling diagnostics %s/%s\\n' "$1" "$2"; }
wait_for_pod_scheduling database backup
'''
        result = subprocess.run(["bash", "-c", script, "test", str(ROOT / "tests/integration/lib.bash")],
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("execution has not started", result.stderr)
        self.assertIn("scheduling diagnostics database/backup", result.stdout)

    def test_cpu_report_counts_init_requests_and_excludes_finished_pods(self):
        data = {"nodes": [{"metadata": {"name": "node"}, "status": {"allocatable": {"cpu": "4"}}}],
                "pods": [
                    {"metadata": {"namespace": "database"}, "status": {"phase": "Running"},
                     "spec": {"nodeName": "node", "containers": [{"resources": {"requests": {"cpu": "200m"}}}],
                              "initContainers": [{"resources": {"requests": {"cpu": "800m"}}}]}},
                    {"metadata": {"namespace": "finished"}, "status": {"phase": "Succeeded"},
                     "spec": {"nodeName": "node", "containers": [{"resources": {"requests": {"cpu": "2"}}}]}},
                    {"metadata": {"namespace": "backup"}, "status": {"phase": "Pending"},
                     "spec": {"containers": [{"resources": {"requests": {"cpu": "100m"}}}]}},
                ]}
        result = subprocess.run([sys.executable, str(ROOT / "tests/integration/resource-budget.py")],
                                input=json.dumps(data), capture_output=True, text=True, check=True)
        self.assertIn("database: 800m", result.stdout)
        self.assertIn("800m requested, 4000m allocatable, 3200m free", result.stdout)
        self.assertIn("unscheduled Pods: 100m requested", result.stdout)
        self.assertNotIn("finished:", result.stdout)

    def test_duration_units(self):
        for value, seconds in (("30s", 30), ("5m", 300), ("1h", 3600)):
            with self.subTest(value=value):
                self.assertEqual(BUILDER["response_ttl_seconds"](value), seconds)

    def test_invalid_durations_fail(self):
        for value in (
            None,
            True,
            300,
            "",
            "0s",
            "-1m",
            "1.5s",
            "1m30s",
            "5",
            "5d",
            "9223372037s",
        ):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    BUILDER["response_ttl_seconds"](value)


    def test_http_and_command_errors_do_not_prove_network_isolation(self):
        script = '''
source "$1"
test_exit="$2"
kube() { return "$test_exit"; }
verify_connection probe workspace block unused
'''
        for code in (0, 1, 6, 7, 22, 28):
            with self.subTest(exit_code=code):
                result = subprocess.run(
                    ["bash", "-c", script, "test",
                     str(ROOT / "tests/integration/verify-network.bash"), str(code)],
                    capture_output=True, text=True, check=True,
                )
                expected = "PASS" if code in (7, 28) else "FAIL"
                self.assertTrue(result.stdout.startswith(f"{expected} probe"), result.stdout)


if __name__ == "__main__":
    unittest.main()
