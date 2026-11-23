# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Check Pod cleanup during virtual cluster hibernation."""

import json
import runpy
import unittest

from helpers import ROOT


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


if __name__ == "__main__":
    unittest.main()
