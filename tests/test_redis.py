# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Check Redis snapshot consistency and bounded failure handling."""

from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
import runpy
import unittest
from unittest.mock import patch

from helpers import ROOT


class RedisSnapshotTests(unittest.TestCase):
    def capture(self, fault=None, abandoned=False):
        module = runpy.run_path(str(ROOT / "scripts/redis-snapshot.py"))
        source = module["snapshots"]["SOURCE"]
        clock = [0]
        paused = [False]
        saved = [False]
        calls = []
        points = {"old": {"metadata": {"name": "old", "uid": "old", "creationTimestamp": "a",
                                      "labels": {module["LABEL"]: "cache", source: "pvc-current", module["VERIFIED"]: "true"}},
                          "spec": {"source": {"persistentVolumeClaimName": "data"}},
                          "status": {"readyToUse": True}}}
        commands = []
        if abandoned:
            points["abandoned"] = deepcopy(points["old"])
            points["abandoned"]["metadata"].update(name="abandoned", uid="abandoned")
            del points["abandoned"]["metadata"]["labels"][module["VERIFIED"]]

        class Redis:
            def command(self, *args):
                commands.append(args)
                if args == ("INFO", "server"):
                    return "run_id:" + ("replacement" if fault == "restart" and saved[0] else "original")
                if args == ("INFO", "persistence"):
                    return "rdb_bgsave_in_progress:0\nrdb_last_bgsave_status:" + ("err" if fault == "disk" else "ok")
                if args[:2] == ("CLIENT", "PAUSE"):
                    paused[0] = True
                if args == ("CLIENT", "UNPAUSE"):
                    paused[0] = False
                if args == ("BGSAVE",):
                    assert paused[0], "A saved RDB needs a write pause"
                    if fault == "save":
                        raise RuntimeError("save failed")
                    saved[0] = True
                    return "Background saving started"
                return "OK"

        class API:
            def call(self, method, path, body=None):
                calls.append((method, path, body))
                if "/volumesnapshotclasses/" in path:
                    return {"deletionPolicy": "Delete"}
                if "/persistentvolumeclaims/" in path:
                    return {"metadata": {"uid": "pvc-current"}, "status": {"phase": "Bound"}}
                if "/pods/" in path:
                    return {"metadata": {"uid": "pod"},
                            "spec": {"volumes": [{"name": "storage", "persistentVolumeClaim": {"claimName": "data"}}],
                                     "containers": [{"volumeMounts": [{"name": "storage", "mountPath": "/data"}]}]},
                            "status": {"conditions": [{"type": "Ready", "status": "True"}]}}
                if method == "POST":
                    assert paused[0] and saved[0], "Capture must follow the disk save while writes are paused"
                    point = deepcopy(body)
                    point["metadata"].update(name="new", uid="new", creationTimestamp="z", resourceVersion="1")
                    point["status"] = {"readyToUse": True}
                    if fault == "csi":
                        point["status"] = {"error": {"message": "snapshot failed"}}
                    points["new"] = point
                    if fault == "expired":
                        clock[0] = 661
                    return point
                if method == "PATCH":
                    assert body["metadata"]["uid"] == "new" and body["metadata"]["resourceVersion"] == "1"
                    points["new"]["metadata"]["labels"].update(body["metadata"]["labels"])
                    return points["new"]
                if method == "DELETE":
                    name = path.rsplit("/", 1)[-1]
                    assert body["preconditions"]["uid"] == points[name]["metadata"]["uid"]
                    del points[name]
                    return {}
                if "?" in path:
                    return {"items": list(points.values())}
                return points[path.rsplit("/", 1)[-1]]

        failure = None
        with patch("time.monotonic", side_effect=lambda: clock[0]), redirect_stdout(StringIO()):
            try:
                module["capture"](API(), Redis(), "lab", "cache", "data", "snapshots", 1)
            except RuntimeError as error:
                failure = error
        self.assertFalse(paused[0], "Every error path must release the Redis write pause")
        return points, calls, commands, failure

    def test_successful_capture_releases_writes_and_applies_retention(self):
        points, _, commands, failure = self.capture()
        self.assertIsNone(failure)
        self.assertEqual(set(points), {"new"})
        self.assertIn(("CLIENT", "PAUSE", 660000, "WRITE"), commands)
        self.assertEqual(commands[-1], ("CLIENT", "UNPAUSE"))
        self.assertEqual(points["new"]["metadata"]["labels"]["datalabs.versioneer.at/redis-snapshot-verified"], "true")

    def test_save_or_restart_failure_does_not_create_a_snapshot(self):
        for fault in ("save", "disk", "restart"):
            with self.subTest(fault=fault):
                points, calls, _, failure = self.capture(fault)
                self.assertIsInstance(failure, RuntimeError)
                self.assertEqual(set(points), {"old"})
                self.assertFalse(any(method == "POST" for method, _, _ in calls))

    def test_expired_pause_rejects_capture_and_keeps_previous_recovery_point(self):
        points, _, _, failure = self.capture("expired")
        self.assertIn("pause expired", str(failure))
        self.assertEqual(set(points), {"old"})

    def test_csi_failure_keeps_previous_recovery_point_and_releases_writes(self):
        points, calls, _, failure = self.capture("csi")
        self.assertIsInstance(failure, RuntimeError)
        self.assertIn("old", points)
        self.assertFalse(any(method == "DELETE" for method, _, _ in calls))

    def test_abandoned_ready_capture_is_removed_without_pruning_a_verified_point(self):
        points, calls, _, failure = self.capture("save", abandoned=True)
        self.assertIsInstance(failure, RuntimeError)
        self.assertEqual(set(points), {"old"})
        self.assertEqual(sum(method == "DELETE" for method, _, _ in calls), 1)


if __name__ == "__main__":
    unittest.main()
