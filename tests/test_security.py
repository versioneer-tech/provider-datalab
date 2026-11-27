# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Check release identity, scan failures, and supported-release selection."""

import io
from copy import deepcopy
from contextlib import redirect_stdout
from datetime import date
import json
import runpy
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SECURITY = runpy.run_path(str(ROOT / "scripts/security.py"))
RELEASE = runpy.run_path(str(ROOT / "scripts/release.py"))
INSTALLER = runpy.run_path(str(ROOT / "scripts/install-tools.py"))
UPDATES = runpy.run_path(str(ROOT / "scripts/check-image-updates.py"))
DIGEST = "sha256:" + "a" * 64


def release(tag, **values):
    return {"tag_name": tag, "draft": False, "prerelease": "-" in tag, **values}


def report(*findings, os_info=None):
    return {"Metadata": {"OS": os_info} if os_info is not None else {},
            "Results": [{"Type": "gobinary", "Packages": [{"Name": "stdlib", "Version": "v1.27.1"}],
                         "Vulnerabilities": list(findings)}]}


class ReleaseSelectionTests(unittest.TestCase):
    def selected(self, tags, manual=""):
        return [item["tag"] for item in SECURITY["select_releases"]([release(tag) for tag in tags], manual)["include"]]

    def test_versions_supersede_older_rcs_and_exclude_older_lines(self):
        tags = ["0.12.4", "0.12.5", "1.9.0", "1.10.0", "1.10.0-rc.9", "1.11.0-rc.2", "1.11.0-rc.10"]
        self.assertEqual(self.selected(tags), ["1.10.0", "1.11.0-rc.10"])

    def test_without_stable_only_newest_rc_is_selected(self):
        self.assertEqual(self.selected(["0.11.0", "0.12.5", "1.0.0-rc.1", "1.0.0-rc.2", "1.0.0-alpha.3"]), ["1.0.0-rc.2"])

    def test_manual_selection_rejects_unknown_and_draft_tags(self):
        self.assertEqual(self.selected(["1.0.0", "1.1.0"], "1.0.0,1.0.0"), ["1.0.0"])
        with self.assertRaises(ValueError):
            self.selected(["1.0.0"], "2.0.0")
        with self.assertRaises(ValueError):
            SECURITY["select_releases"]([release("1.0.0", draft=True)], "1.0.0")

    def test_empty_release_evidence_fails(self):
        with self.assertRaises(ValueError):
            SECURITY["select_releases"]([])
        with self.assertRaises(ValueError):
            self.selected(["0.12.5", "0.12.6-rc.1"])

    def test_published_package_without_release_assets_is_not_silently_omitted(self):
        selected = SECURITY["select_releases"]([release("1.0.0-rc.1")], published_tags=["0.13.5", "latest"])
        self.assertEqual([item["tag"] for item in selected["include"]], ["0.13.5", "1.0.0-rc.1"])


class ScanPolicyTests(unittest.TestCase):
    def test_critical_and_fixable_high_block(self):
        findings = [{"VulnerabilityID": "test-critical", "Severity": "CRITICAL"},
                    {"VulnerabilityID": "test-high", "Severity": "HIGH", "FixedVersion": "2.0"},
                    {"VulnerabilityID": "test-unfixed", "Severity": "HIGH"},
                    {"VulnerabilityID": "test-medium", "Severity": "MEDIUM"}]
        result = SECURITY["assess"](report(*findings))
        self.assertEqual([item["VulnerabilityID"] for item in result["blocking"]], ["test-critical", "test-high"])
        self.assertEqual([item["VulnerabilityID"] for item in result["unfixed_high"]], ["test-unfixed"])

    def test_image_inventory_includes_bare_names_without_host_ports(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for directory in ("composition", "dependencies", "templates", "tests/integration/manifests"):
                (root / directory).mkdir(parents=True)
            (root / "composition/defaults.py").write_text('image = "registry:3.1.2"\nhost = "0.0.0.0:5000"\n')
            (root / "templates/auth.yaml").write_text("image: httpd:2.4.71-alpine\n")
            for name in ("functions.yaml", "02-providers.yaml"):
                (root / "dependencies" / name).write_text("---\n")
            (root / "tests/integration/manifests/kind.yaml").write_text("nodes: []\n")
            self.assertEqual(SECURITY["external_images"](root), ["httpd:2.4.71-alpine", "registry:3.1.2"])

    def test_missing_inventory_or_end_of_support_fails(self):
        for data in ({"Results": []}, report(os_info={"Family": "alpine", "Name": "3.10", "EOSL": True})):
            with self.subTest(data=data), self.assertRaises(ValueError):
                SECURITY["assess"](data, image=True)

    def test_scratch_go_images_have_no_os_inventory(self):
        self.assertEqual(SECURITY["assess"](report(), image=True)["packages"], 1)

    def test_image_inventory_requires_os_packages_and_go_standard_library(self):
        with self.assertRaises(ValueError):
            SECURITY["assess"](report(os_info={"Family": "debian", "Name": "13"}), image=True)
        data = report()
        data["Results"][0]["Packages"] = [{"Name": "example.com/module", "Version": "v1.0.0"}]
        with self.assertRaises(ValueError):
            SECURITY["assess"](data, image=True)

    def test_scanner_failure_retains_failed_summary(self):
        with tempfile.TemporaryDirectory() as temporary:
            candidate = Path(temporary) / "candidate"
            candidate.mkdir()
            (candidate / "security-manifest.json").write_text("{}")
            reports = Path(temporary) / "reports"
            with redirect_stdout(io.StringIO()):
                self.assertEqual(SECURITY["scan"](candidate, reports), 1)
            self.assertFalse(json.loads((reports / "scan-summary.json").read_text())["passed"])


class VulnerabilityExceptionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / "vulnerability-exceptions.json"
        self.reference = "example.com/test/image@" + DIGEST
        self.finding = {"VulnerabilityID": "CVE-2026-1000", "PkgName": "test-package", "InstalledVersion": "1.0",
                        "PkgIdentifier": {"PURL": "pkg:generic/test-package@1.0"}, "Target": "/usr/bin/test-service",
                        "Severity": "CRITICAL"}
        self.review = {"owner": "Test maintainer", "reason": "Temporary acceptance",
                       "mitigation": "Use synthetic data in an isolated test environment", "tracking": "SECURITY.md",
                       "accepted_on": "2026-11-26", "expires_on": "2026-12-26"}
        self.entry = {"image": self.reference}

    def load(self, entries=None, **review):
        self.path.write_text(json.dumps({"schema": 3, **self.review, **review,
                                        "exceptions": entries if entries is not None else [self.entry]}))
        return SECURITY["load_vulnerability_exceptions"](self.path)

    def assess(self, finding=None, reference=None, today=date(2026, 11, 26)):
        data = report(finding or self.finding)
        data["Results"][0]["Target"] = (finding or self.finding)["Target"]
        assessment = SECURITY["assess"](data, image=True)
        return SECURITY["apply_vulnerability_exceptions"](
            assessment, reference or self.reference, self.load(), today)

    def test_current_critical_and_fixable_high_are_retained_as_accepted(self):
        for severity in ("CRITICAL", "HIGH"):
            with self.subTest(severity=severity):
                self.finding.update(Severity=severity, FixedVersion="2.0")
                result = self.assess()
                self.assertEqual(result["blocking"], [])
                self.assertEqual(result["accepted"][0]["VulnerabilityID"], self.finding["VulnerabilityID"])
                self.assertEqual(result["accepted"][0]["exception"]["owner"], "Test maintainer")
                self.assertEqual(result["accepted"][0]["exception"]["expires_on"], "2026-12-26")
                grouped = self.assess({**self.finding, "VulnerabilityID": "CVE-2026-3000"})
                self.assertEqual(len(grouped["accepted"]), 1)

    def test_new_findings_are_accepted_only_for_the_same_image_digest(self):
        changes = {"VulnerabilityID": "CVE-2026-2000", "PkgName": "other-package", "InstalledVersion": "1.1",
                   "PkgIdentifier": {"PURL": "pkg:generic/other-package@1.0"}, "Target": "/usr/bin/other-service",
                   "Severity": "HIGH"}
        for field, value in changes.items():
            changed = {**self.finding, field: value, "FixedVersion": "2.0"}
            with self.subTest(field=field):
                result = self.assess(changed)
                self.assertEqual(result["blocking"], [])
                self.assertEqual(len(result["accepted"]), 1)
        for reference in ("example.com/other/image@" + DIGEST, "example.com/test/image@sha256:" + "b" * 64):
            with self.subTest(reference=reference):
                self.assertEqual(len(self.assess(reference=reference)["blocking"]), 1)

    def test_exceptions_apply_only_within_the_review_period(self):
        self.assertEqual(len(self.assess(today=date(2026, 12, 25))["accepted"]), 1)
        self.assertEqual(len(self.assess(today=date(2026, 11, 25))["blocking"]), 1)
        expired = self.assess(today=date(2026, 12, 26))
        self.assertEqual(len(expired["blocking"]), 1)
        self.assertEqual(len(expired["expired_exceptions"]), 1)

    def test_invalid_or_duplicate_policy_fails(self):
        for field, value in (("owner", ""), ("expires_on", "2026-11-25"), ("accepted_on", "invalid")):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.load(**{field: value})
        for reference in ("example.com/test/image:1.0", "", None):
            with self.subTest(reference=reference), self.assertRaises(ValueError):
                self.load([{"image": reference}])
        with self.assertRaises(ValueError):
            self.load([self.entry, self.entry])

    def test_external_exceptions_cannot_accept_source_or_inventory_failures(self):
        assessment = SECURITY["assess"](report(self.finding))
        result = SECURITY["apply_vulnerability_exceptions"](assessment, None, self.load(), date(2026, 11, 26))
        self.assertEqual(len(result["blocking"]), 1)
        with self.assertRaises(ValueError):
            SECURITY["assess"](report(self.finding, os_info={"Family": "debian", "Name": "1", "EOSL": True}), image=True)

    def test_publication_rechecks_expiry_and_policy_changes(self):
        self.load()
        (self.root / "source.json").write_text(json.dumps(report()))
        data = report(self.finding)
        data["Results"][0]["Target"] = self.finding["Target"]
        (self.root / "external-00.json").write_text(json.dumps(data))
        policy_hash = SECURITY["checksum"](self.path)
        summary = {"vulnerability_exceptions_sha256": policy_hash, "files": {self.path.name: policy_hash}}
        verify = SECURITY["verify_scan_policy"]
        with patch.dict(verify.__globals__, {"VULNERABILITY_EXCEPTIONS": self.path}):
            verify(summary, self.root, [{"immutable": self.reference, "usage": "runtime"}], date(2026, 12, 25))
            with self.assertRaises(ValueError):
                verify(summary, self.root, [{"immutable": self.reference, "usage": "runtime"}], date(2026, 12, 26))
            self.path.write_text(self.path.read_text() + "\n")
            with self.assertRaises(ValueError):
                verify(summary, self.root, [{"immutable": self.reference, "usage": "runtime"}], date(2026, 12, 25))


class QualificationTests(unittest.TestCase):
    def test_uncertain_registry_lookup_cannot_publish(self):
        manifest = {"image": "example.com/test/package", "image_digest": DIGEST}
        failed = subprocess.CompletedProcess([], 1, stderr="proxy returned 404")
        module = RELEASE["SECURITY"]
        with patch.object(module, "verify", return_value=manifest), \
                patch.object(module, "run") as publish_command, \
                patch.object(RELEASE["subprocess"], "run", return_value=failed):
            with self.assertRaises(ValueError):
                RELEASE["publish"]("test/repository", Path("candidate"), Path("reports"),
                                   "1.0.0", "a" * 40, 1, 2, 3)
        publish_command.assert_not_called()

    def test_older_and_prerelease_versions_cannot_move_latest_backward(self):
        published = [release("1.9.0"), release("1.10.0"), release("2.0.0-rc.1")]
        self.assertTrue(RELEASE["advances_latest"]("1.11.0", published))
        self.assertFalse(RELEASE["advances_latest"]("1.9.1", published))
        self.assertFalse(RELEASE["advances_latest"]("2.0.0-rc.2", published))

    def test_pr_and_incomplete_runs_do_not_qualify(self):
        workflow = {"head_sha": "a" * 40, "head_branch": "main", "event": "push", "conclusion": "success"}
        jobs = [{"name": name, "conclusion": "success"} for name in
                ("changes", "documentation", "runtime_checks", "security_checks", "required_checks")]
        qualify = RELEASE["qualified_run"]
        self.assertTrue(qualify(workflow, "a" * 40, "main", jobs))
        self.assertTrue(qualify({**workflow, "event": "workflow_dispatch"}, "a" * 40, "main", jobs))
        for change in ({"event": "pull_request"}, {"head_sha": "b" * 40}, {"head_branch": "topic"}):
            self.assertFalse(qualify({**workflow, **change}, "a" * 40, "main", jobs))
        for result in ("skipped", "cancelled", "failure"):
            self.assertFalse(qualify(workflow, "a" * 40, "main", [
                {**job, "conclusion": result} if job["name"] == "runtime_checks" else job for job in jobs]))


class ImageUpdateTests(unittest.TestCase):
    def test_test_package_report_uses_locks_and_does_not_update_them(self):
        before = {name: (ROOT / name).read_bytes() for name in SECURITY["TEST_LOCKFILES"]}
        output = subprocess.CompletedProcess([], 0, "\nexample.test/module v1.0.0 v1.1.0\n")
        with patch("urllib.request.urlopen", side_effect=lambda *a, **k: io.BytesIO(b'{"info":{"version":"99.0.0"}}')), \
                patch.object(UPDATES["subprocess"], "run", return_value=output) as command:
            results = UPDATES["test_package_updates"](ROOT)
        self.assertIn("-mod=readonly", command.call_args.args[0])
        self.assertTrue(any(item["package"] == "boto3" and item["update_available"] for item in results))
        self.assertTrue(any(item["package"] == "example.test/module" for item in results))
        self.assertEqual(before, {name: (ROOT / name).read_bytes() for name in before})

    def test_versions_keep_variants_and_prereleases_separate(self):
        result = UPDATES["newer_tags"]("v1.36.6-alpine", [
            "v1.36.7-alpine", "v1.36.8-rc.1-alpine", "v1.38.0-alpine",
            "v1.37.0-alpine", "v2.0.0-alpine", "v1.99.0-bookworm", "latest"])
        self.assertEqual(result, {"patch_or_rebuild": "v1.36.7-alpine", "minor": "v1.38.0-alpine",
                                  "major": "v2.0.0-alpine"})

    def test_dated_database_images_keep_os_and_type(self):
        result = UPDATES["newer_tags"]("17.12-3.7.0-202611231010-standard-trixie", [
            "17.12-3.7.0-202611301010-standard-trixie", "17.12-3.7.0-202611301010-minimal-trixie",
            "17.12-3.7.0-202611301010-standard-bookworm", "18.7-3.7.0-202611231010-standard-trixie"])
        self.assertEqual(result, {"patch_or_rebuild": "17.12-3.7.0-202611301010-standard-trixie",
                                  "major": "18.7-3.7.0-202611231010-standard-trixie"})

    def test_changed_digest_is_reported_without_changing_reference(self):
        reference = "registry:3.1.2@" + DIGEST
        def registry(*arguments):
            return "sha256:" + "b" * 64 if arguments[0] == "digest" else "3.1.2\n3.1.3"
        with patch.dict(UPDATES["check_reference"].__globals__, {"crane": registry}):
            result = UPDATES["check_reference"](reference)
        self.assertEqual(result["reference"], reference)
        self.assertTrue(result["digest_changed"])
        self.assertEqual(result["newer_tags"], {"patch_or_rebuild": "3.1.3"})

    def test_registry_error_does_not_omit_other_images(self):
        def check(reference):
            if reference == "unavailable:1.0":
                raise subprocess.TimeoutExpired("crane", 90)
            return {"reference": reference, "digest_changed": False}
        results = UPDATES["check_all"](["unavailable:1.0", "available:1.0"], check)
        self.assertIn("error", results[0])
        self.assertEqual(results[1]["reference"], "available:1.0")

    def test_non_versioned_tags_need_no_tag_listing(self):
        def registry(*arguments):
            self.assertEqual(arguments[0], "digest")
            return DIGEST
        with patch.dict(UPDATES["check_reference"].__globals__, {"crane": registry}):
            result = UPDATES["check_reference"]("example.test/image:distroless-v1.38.9@" + DIGEST)
        self.assertEqual(result["version_check"], "same_tag_digest_only")
        self.assertFalse(result["digest_changed"])


class IntegrityTests(unittest.TestCase):
    def test_registry_retries_errors_but_rejects_invalid_identity(self):
        with patch.dict(SECURITY["registry_digest"].__globals__, {
                "run": unittest.mock.Mock(side_effect=[subprocess.TimeoutExpired("crane", 90),
                    subprocess.CompletedProcess([], 0, DIGEST + "\n")])}), patch("time.sleep"):
            self.assertEqual(SECURITY["registry_digest"]("registry:3.1.2"), DIGEST)
        with patch.dict(SECURITY["registry_digest"].__globals__, {
                "run": lambda *a, **k: subprocess.CompletedProcess([], 0, "unexpected")}), self.assertRaises(ValueError):
            SECURITY["registry_digest"]("registry:3.1.2")

    def test_source_snapshot_skips_links_and_rejects_credential_stores(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source"
            source.mkdir()
            (source / "plain.py").write_text("pass\n")
            (source / "linked").symlink_to(Path(temporary), target_is_directory=True)
            def git_paths(*args, **kwargs):
                return subprocess.CompletedProcess([], 0, b"plain.py\0linked/private.py\0")
            with patch.dict(SECURITY["source_paths"].__globals__, {"run": git_paths}):
                self.assertEqual(SECURITY["source_paths"](source), [Path("plain.py")])
            def credential_path(*args, **kwargs):
                return subprocess.CompletedProcess([], 0, b".aws/credentials\0")
            with patch.dict(SECURITY["source_paths"].__globals__, {"run": credential_path}):
                with self.assertRaises(ValueError):
                    SECURITY["source_paths"](source)

    def test_fixture_exception_rejects_changed_content_and_other_rules(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            fixture = source / "fixture.yaml"
            fixture.write_text("synthetic")
            exceptions = {"fixture.yaml": {"rules": ["generic-api-key"], "sha256": SECURITY["checksum"](fixture)}}
            finding = {"File": str(fixture), "RuleID": "generic-api-key"}
            self.assertTrue(SECURITY["secret_is_fixture"](finding, source, exceptions))
            self.assertFalse(SECURITY["secret_is_fixture"]({**finding, "RuleID": "private-key"}, source, exceptions))
            fixture.write_text("changed")
            self.assertFalse(SECURITY["secret_is_fixture"](finding, source, exceptions))

    def test_source_archive_rejects_links_and_escape_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            for name, kind in [("../outside", tarfile.REGTYPE), ("/outside", tarfile.REGTYPE), ("link", tarfile.SYMTYPE)]:
                archive = Path(temporary) / "source.tar"
                with tarfile.open(archive, "w") as bundle:
                    member = tarfile.TarInfo(name)
                    member.type = kind
                    bundle.addfile(member)
                with self.subTest(name=name), self.assertRaises(ValueError):
                    SECURITY["unpack_source"](archive, Path(temporary) / "out")

    def test_changed_candidate_and_evidence_cannot_be_published(self):
        with tempfile.TemporaryDirectory() as temporary:
            candidate = Path(temporary)
            names = ("datalab.xpkg", "source.tar.gz", "package.cdx.json", "external-components.json")
            for name in names:
                (candidate / name).write_text("original")
            manifest = {"schema": 1, "scope": "production", "version": "1.0.0", "commit": "a" * 40, "worktree_dirty": False,
                        "image": SECURITY["REPOSITORY"], "image_digest": DIGEST,
                        "files": {name: SECURITY["checksum"](candidate / name) for name in names}}
            (candidate / "security-manifest.json").write_text(json.dumps(manifest))
            with patch.dict(SECURITY["verify"].__globals__, {"run": lambda *a, **k: subprocess.CompletedProcess([], 0, DIGEST + "\n")}):
                self.assertEqual(SECURITY["verify"](candidate)["commit"], "a" * 40)
                for name in names:
                    (candidate / name).write_text("changed")
                    with self.subTest(name=name), self.assertRaises(ValueError):
                        SECURITY["verify"](candidate)
                    (candidate / name).write_text("original")
                (candidate / "scan-summary.json").write_text(json.dumps({"passed": True, "manifest_sha256": "wrong"}))
                with self.assertRaises(ValueError):
                    SECURITY["verify"](candidate, candidate)
                with self.assertRaises(ValueError):
                    SECURITY["verify"](candidate, version="2.0.0")
                (candidate / "scan-summary.json").write_text(json.dumps({"passed": True, "scope": "test",
                    "manifest_sha256": SECURITY["checksum"](candidate / "security-manifest.json")}))
                with self.assertRaisesRegex(ValueError, "does not approve"):
                    SECURITY["verify"](candidate, candidate)

    def test_bad_download_does_not_replace_installed_tool(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary)
            (destination / "tool").write_bytes(b"existing")
            with patch("urllib.request.urlopen", return_value=io.BytesIO(b"tampered")):
                with self.assertRaises(ValueError):
                    INSTALLER["install"]("tool", {"url": "https://example.com/tool", "sha256": "0" * 64}, destination)
            self.assertEqual((destination / "tool").read_bytes(), b"existing")


if __name__ == "__main__":
    unittest.main()
