# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Check integration target selection and capability probes."""

import runpy
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from helpers import ROOT


class HarnessTests(unittest.TestCase):
    def test_explicit_snapshot_class_makes_failed_prerequisites_fatal(self):
        script = '''
set -euo pipefail
export PROVIDER_DATALAB_CLUSTER=existing PROVIDER_DATALAB_SNAPSHOT_CLASS="$2"
source "$1"
check_volume_snapshot_settings() { printf 'API unavailable\\n' >&2; return 2; }
check_snapshot_observer_access() { printf 'unexpected observer check\\n' >&2; }
if snapshot_tests_available; then printf 'snapshots enabled\\n'; fi
printf 'continued after probe\\n'
'''
        for snapshot_class in ("", "test-snapshots"):
            with self.subTest(snapshot_class=snapshot_class):
                result = subprocess.run(["bash", "-c", script, "test",
                                         str(ROOT / "tests/integration/snapshots.bash"), snapshot_class],
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 1 if snapshot_class else 0)
                self.assertNotIn("unexpected observer check", result.stderr)
                if snapshot_class:
                    self.assertIn("Required snapshot setup is incomplete", result.stderr)
                    self.assertNotIn("SKIPPED", result.stdout)
                    self.assertNotIn("continued", result.stdout)
                else:
                    self.assertIn("SKIPPED", result.stdout)
                    self.assertIn("continued after probe", result.stdout)

    def test_virtual_target_can_skip_network_traffic_checks_without_a_probe(self):
        script = '''
export PROVIDER_DATALAB_CLUSTER=existing PROVIDER_DATALAB_SKIP_NETWORK_POLICY=1
source "$1"
probe_network_policy() { printf 'unexpected network probe\n' >&2; return 0; }
network_policy_tests_available
'''
        result = subprocess.run(["bash", "-c", script, "test", str(ROOT / "tests/integration/network-policy.bash")],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("SKIPPED: NetworkPolicy traffic tests", result.stdout)
        self.assertNotIn("unexpected network probe", result.stderr)

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

    def test_network_policy_probe_requires_blocking_and_recovery(self):
        script = """
set -euo pipefail
source "$1"
MANIFEST_DIR=/test/manifests
NETWORK_SERVER_IMAGE=test-server
NETWORK_CLIENT_IMAGE=test-client
fault="$2"
policy=0
render_template() { printf 'fixture'; }
sleep() { SECONDS=$((SECONDS + 30)); }
kube() {
  case "$*" in
    'get namespace '*) return 0 ;;
    'get pod '*) printf '10.0.0.2' ;;
    'apply -f -')
      local manifest
      manifest="$(cat)"
      if [[ "$manifest" == *NetworkPolicy* ]]; then
        [[ "$fault" != apply-failed ]] || return 1
        policy=1
      fi ;;
    'exec '*)
      [[ "$fault" != baseline-failed ]] || return 7
      if [[ "$policy" == 1 && "$fault" != unenforced ]]; then return 28; fi
      [[ "$fault" != recovery-failed || "$policy" != 2 ]] || return 28 ;;
    'delete networkpolicy/'*) policy=2 ;;
    'delete namespace '*) printf 'probe namespace removed\\n' ;;
    *) return 0 ;;
  esac
}
probe_network_policy
"""
        for fault in ("none", "unenforced", "baseline-failed", "apply-failed", "recovery-failed"):
            with self.subTest(fault=fault):
                result = subprocess.run(["bash", "-c", script, "test",
                                         str(ROOT / "tests/integration/network-policy.bash"), fault],
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode == 0, fault == "none", result.stderr)

    def test_network_traffic_checks_follow_the_probe_on_every_target(self):
        script = """
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
probe_result="$3"
probe_network_policy() { return "$probe_result"; }
main
"""
        for mode in ("kind", "existing"):
            for enforced in (True, False):
                with self.subTest(mode=mode, enforced=enforced):
                    result = subprocess.run(["bash", "-c", script, "test",
                                             str(ROOT / "tests/integration/verify-network.bash"), mode,
                                             "0" if enforced else "1"], capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0 if enforced or mode == "existing" else 1, result.stderr)
                    if enforced:
                        self.assertIn("network traffic checks", result.stdout)
                        self.assertNotIn("SKIPPED", result.stdout)
                    elif mode == "existing":
                        self.assertIn("resource limit checks", result.stdout)
                        self.assertNotIn("network traffic checks", result.stdout)
                        self.assertIn("SKIPPED: NetworkPolicy traffic tests", result.stdout)

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
        for control_plane, allowed in ((None, ["test-snapshots"]),
                                       ("test-snapshots", ["test-snapshots"]),
                                       ("test-local", ["test-snapshots", "test-local"])):
            result = configure([{"data": {}}], "test-snapshots", "10.20.0.0/16", "10.30.0.0/16", control_plane)
            self.assertEqual(result[0]["data"]["vcluster"]["storageClassName"], control_plane or "test-snapshots")
            self.assertEqual(result[0]["data"]["volumes"]["storageClasses"], {
                "allowed": allowed, "default": "test-snapshots",
            })
        with self.assertRaises(ValueError):
            configure(documents, "test-storage", "invalid", "10.30.0.0/16")

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
