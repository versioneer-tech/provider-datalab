#!/usr/bin/env python3
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Build, scan, and verify saved Configuration packages without publication."""

import argparse
import ast
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from datetime import UTC, date, datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
VERSION = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-(alpha|beta|rc)\.(0|[1-9]\d*))?")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
IMAGE = re.compile(r"(?:[a-z0-9.-]+(?::[0-9]+)?/)*[a-zA-Z0-9_.-]+:[a-zA-Z0-9_.-]+(?:@sha256:[0-9a-f]{64})?")
REPOSITORY = "ghcr.io/versioneer-tech/provider-datalab"
LOCKFILES = ("scripts/requirements.txt", "docs/requirements.txt", "tools/requirements.txt")
TEST_LOCKFILES = ("tests/s3/requirements.txt", "tests/vcluster/requirements.txt", "tests/vcluster/tooling/requirements.txt")
VULNERABILITY_EXCEPTIONS = ROOT / "scripts/vulnerability-exceptions.json"


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def checksum(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def run(arguments, **kwargs):
    return subprocess.run([str(argument) for argument in arguments], check=True, **kwargs)


def tool(name):
    return ROOT / "build/tools" / name


def registry_digest(reference):
    for attempt in range(3):
        try:
            result = run([tool("crane"), "digest", "--platform", "linux/amd64", reference],
                         capture_output=True, text=True, timeout=90)
            digest = result.stdout.strip()
            if not DIGEST.fullmatch(digest):
                raise ValueError(f"Invalid external image digest: {reference}")
            return digest
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))


def scan_command(arguments, log):
    # A bounded retry handles registry and vulnerability database interruptions.
    for attempt in range(3):
        with log.open("a") as output:
            result = subprocess.run([str(argument) for argument in arguments], stdout=output, stderr=subprocess.STDOUT)
        if result.returncode == 0:
            return
        if attempt < 2:
            time.sleep(2 * (attempt + 1))
    raise subprocess.CalledProcessError(result.returncode, arguments)


def source_paths(source):
    private = {".aws", ".docker", ".kube", ".ssh", ".config", ".git-credentials", ".netrc", ".npmrc", ".pypirc"}
    output = run(["git", "ls-files", "--cached", "--others", "--exclude-standard",
                  *["--exclude=" + name for name in sorted(private)], "-z"],
                 cwd=source, capture_output=True).stdout
    paths = sorted({Path(name.decode()) for name in output.split(b"\0") if name})
    if any(path.parts[0] in private or path.name.endswith(".kubeconfig") or path.name == "kubeconfig" for path in paths):
        raise ValueError("A credential store is tracked or unignored; source checks cannot read it")
    # Never copy local tool state or follow a link into a credential directory.
    return [path for path in paths if not path.is_absolute() and ".." not in path.parts
            and path.parts[0] not in {".git", ".codex", ".aws", ".agents", "build", "dist", "site", ".venv"}
            and not any((source / Path(*path.parts[:index])).is_symlink() for index in range(1, len(path.parts) + 1))
            and (source / path).is_file()]


def unpack_source(archive, destination):
    with tarfile.open(archive) as bundle:
        for member in bundle:
            path = Path(member.name)
            if not member.isfile() or path.is_absolute() or ".." in path.parts:
                raise ValueError("Unsafe source archive member")
            target = destination / path
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.extractfile(member) as stream, target.open("wb") as output:
                shutil.copyfileobj(stream, output)


def check_package(archive, source):
    found = []
    with tarfile.open(archive) as bundle:
        manifests = json.load(bundle.extractfile("manifest.json"))
        if len(manifests) != 1:
            raise ValueError("Expected one Configuration image")
        for layer in manifests[0]["Layers"]:
            with tarfile.open(fileobj=bundle.extractfile(layer)) as contents:
                for member in contents:
                    if not member.isfile() or member.name not in {"package.yaml", ".up/examples.yaml"}:
                        raise ValueError("Unexpected package content")
                    data = contents.extractfile(member).read()
                    if member.name == "package.yaml":
                        found.extend(item for item in yaml.safe_load_all(data) if item is not None)
                    elif list(yaml.safe_load_all(data)):
                        raise ValueError("Examples are outside this release package")
    expected = [yaml.safe_load((source / name).read_text()) for name in
                ("crossplane.yaml", "xrd.yaml", "composition.yaml")]
    for item in found:
        # Crossplane adds controller status during encoding; status is not a package input.
        if item["kind"] == "CompositeResourceDefinition":
            item.pop("status", None)
    key = lambda item: (item["apiVersion"], item["kind"], item["metadata"]["name"])
    if sorted(found, key=key) != sorted(expected, key=key):
        raise ValueError("Package does not match its source manifests")


def external_images(source, scope="all"):
    references = set()
    for path in (source / "composition").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                value = node.value
                # Bare host:port settings are not container image defaults.
                if IMAGE.fullmatch(value) and ("/" in value or re.fullmatch(
                        r"(?:python|nginx|registry|alpine|busybox):[\w.-]+(?:@sha256:[0-9a-f]{64})?", value)):
                    references.add(value)
    for name in ("functions.yaml", "02-providers.yaml"):
        for document in yaml.safe_load_all((source / "dependencies" / name).read_text()):
            if document and document.get("spec", {}).get("package"):
                references.add(document["spec"]["package"])
    for path in (source / "templates").rglob("*.yaml"):
        for reference in re.findall(r"(?m)^\s*image:\s*['\"]?([^\s'\"]+)", path.read_text()):
            if IMAGE.fullmatch(reference):
                references.add(reference)
    lock = source / "scripts/components.json"
    pins = json.loads(lock.read_text()) if lock.exists() else {}
    references.update(pins["images"][name] for name in pins.get("runtimeImages", []))
    runtime = references.copy()
    if lock.exists():
        references.update(pins["images"].values())
    for path in (source / "tests").rglob("*Dockerfile"):
        references.update(re.findall(r"(?m)^FROM\s+(\S+)", path.read_text()))
    kind = yaml.safe_load((source / "tests/integration/manifests/kind.yaml").read_text())
    references.update(node["image"] for node in kind["nodes"])
    for directory in ("tests/integration", "tests/vcluster", "tests/s3", "examples"):
        for path in (source / directory).rglob("*"):
            if not path.is_file() or path.suffix not in (".yaml", ".bash", ".py"):
                continue
            text = path.read_text()
            if path.suffix == ".py":
                for node in ast.walk(ast.parse(text)):
                    if isinstance(node, ast.Dict):
                        references.update(value.value for key, value in zip(node.keys, node.values)
                                          if isinstance(key, ast.Constant) and key.value == "image"
                                          and isinstance(value, ast.Constant) and isinstance(value.value, str)
                                          and IMAGE.fullmatch(value.value))
            else:
                references.update(reference for reference in re.findall(
                    r"(?m)^\s*image:\s*['\"]?([^\s'\"]+)", text) if IMAGE.fullmatch(reference))
                references.update(reference for reference in re.findall(
                    r"IMAGE:=([^}]+)", text) if IMAGE.fullmatch(reference))
    if not references:
        raise ValueError("No default runtime dependencies found")
    if scope == "production":
        return sorted(runtime)
    if scope == "test":
        return sorted(references - runtime)
    return sorted(references)


def prepare(source, destination, version, commit, allow_dirty=False, scope="production"):
    if not VERSION.fullmatch(version) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("A release version and full source commit are required")
    head = run(["git", "rev-parse", "HEAD"], cwd=source, capture_output=True, text=True).stdout.strip()
    if head != commit:
        raise ValueError("The source commit does not match the checkout")
    dirty = bool(run(["git", "status", "--porcelain"], cwd=source, capture_output=True).stdout)
    if dirty and not allow_dirty:
        raise ValueError("Release candidates require a clean worktree")
    destination.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix="datalab-package-") as temporary:
        package = Path(temporary)
        for name in ("crossplane.yaml", "xrd.yaml", "composition.yaml"):
            shutil.copyfile(source / name, package / name)
        run([sys.executable, source / "scripts/build-composition.py", "--check"])
        run([tool("crossplane"), "xpkg", "build", "--package-root", package,
             "--examples-root", package / "examples", "--package-file", destination / "datalab.xpkg"])
    check_package(destination / "datalab.xpkg", source)
    digest = run([tool("crane"), "digest", "--tarball", destination / "datalab.xpkg"],
                 capture_output=True, text=True).stdout.strip()
    if not DIGEST.fullmatch(digest):
        raise ValueError("Invalid package manifest digest")
    with tarfile.open(destination / "source.tar.gz", "w:gz") as bundle:
        for path in source_paths(source):
            bundle.add(source / path, arcname=str(path), recursive=False)
    images = []
    runtime_images = set(external_images(source, "production"))
    for reference in external_images(source, scope):
        if "@sha256:" not in reference:
            raise ValueError(f"Unpinned image: {reference}")
        resolved = registry_digest(reference)
        repository = reference.split("@")[0].rsplit(":", 1)[0]
        images.append({"declared": reference, "immutable": repository + "@" + resolved,
                       "usage": "runtime" if reference in runtime_images else "test"})
    write_json(destination / "external-components.json", images)
    components = [{"type": "file", "name": name,
                   "hashes": [{"alg": "SHA-256", "content": checksum(source / name)}]}
                  for name in ("crossplane.yaml", "xrd.yaml", "composition.yaml")]
    write_json(destination / "package.cdx.json", {
        "bomFormat": "CycloneDX", "specVersion": "1.6", "version": 1,
        "metadata": {"timestamp": datetime.now(UTC).isoformat(), "component": {
            "type": "application", "name": "provider-datalab", "version": version,
            "bom-ref": REPOSITORY + "@" + digest,
            "hashes": [{"alg": "SHA-256", "content": checksum(destination / "datalab.xpkg")}] },
            "properties": [{"name": "versioneer.at/source-commit", "value": commit}]},
        "components": components,
    })
    write_json(destination / "security-manifest.json", {
        "schema": 1, "scope": scope, "version": version, "commit": commit, "worktree_dirty": dirty,
        "image": REPOSITORY, "image_digest": digest,
        "files": {name: checksum(destination / name) for name in
                  ("datalab.xpkg", "source.tar.gz", "package.cdx.json", "external-components.json")},
        "coverage": {
            "package": "Configuration manifests and embedded Python; no OS or executable runtime",
            "source": "Production scans cover Python build, documentation, audit and hook dependencies; test locks and Go admission tests are checked on use",
            "external": "Pinned production images or test-only images, as selected by scope; shared runtime/test images stay in production",
            "platform_inputs": json.loads((source / "scripts/components.json").read_text())["artifacts"],
            "limits": "Operator overrides, disabled optional vCluster components, host software and deployed cluster state are outside this inventory",
        },
    })


def image_scopes(images, scope="production"):
    if any(item.get("usage") not in {"runtime", "test"} for item in images):
        raise ValueError("Missing external image usage")
    usage = "runtime" if scope == "production" else "test"
    return [(f"external-{index:02d}", item) for index, item in enumerate(images) if item["usage"] == usage]


def verify(candidate, reports=None, version=None, commit=None, allow_dirty=False):
    manifest = json.loads((candidate / "security-manifest.json").read_text())
    if manifest.get("schema") != 1 or manifest["image"] != REPOSITORY:
        raise ValueError("Unsupported security manifest")
    if not VERSION.fullmatch(manifest["version"]) or not re.fullmatch(r"[0-9a-f]{40}", manifest["commit"]):
        raise ValueError("Invalid release identity")
    if version and manifest["version"] != version or commit and manifest["commit"] != commit:
        raise ValueError("Release identity does not match")
    if manifest["worktree_dirty"] and not allow_dirty:
        raise ValueError("A dirty candidate cannot be published")
    required = {"datalab.xpkg", "source.tar.gz", "package.cdx.json", "external-components.json"}
    if set(manifest["files"]) != required:
        raise ValueError("Missing candidate inventory")
    for name, expected in manifest["files"].items():
        if checksum(candidate / name) != expected:
            raise ValueError(f"Candidate checksum does not match: {name}")
    actual = run([tool("crane"), "digest", "--tarball", candidate / "datalab.xpkg"],
                 capture_output=True, text=True).stdout.strip()
    if actual != manifest["image_digest"] or not DIGEST.fullmatch(actual):
        raise ValueError("Package manifest digest does not match")
    if reports is not None:
        summary = json.loads((reports / "scan-summary.json").read_text())
        if (manifest.get("scope") != "production" or summary.get("scope") != "production" or not summary.get("passed") or
                summary["manifest_sha256"] != checksum(candidate / "security-manifest.json")):
            raise ValueError("Scan evidence does not approve this candidate")
        if not summary.get("files"):
            raise ValueError("Missing scan evidence")
        images = json.loads((candidate / "external-components.json").read_text())
        scopes = {"source", *[name for name, _ in image_scopes(images)]}
        required_reports = {f"{scope}{suffix}" for scope in scopes for suffix in (".json", ".cdx.json")}
        required_reports.update({"secrets.json", "secret-assessment.json", VULNERABILITY_EXCEPTIONS.name})
        required_reports.update(name.replace("/", "-") + ".json" for name in LOCKFILES)
        if not required_reports <= summary["files"].keys() or scopes != summary["scopes"].keys():
            raise ValueError("Incomplete scan report or SBOM inventory")
        if summary.get("errors") or any(item["blocking"] for item in summary["scopes"].values()):
            raise ValueError("Blocking findings remain in scan evidence")
        for name, expected in summary["files"].items():
            if Path(name).name != name or checksum(reports / name) != expected:
                raise ValueError("Scan evidence changed")
        verify_scan_policy(summary, reports, images)
    return manifest


def load_vulnerability_exceptions(path=None):
    policy = json.loads((path or VULNERABILITY_EXCEPTIONS).read_text())
    if not isinstance(policy, dict) or policy.get("schema") != 3 or not isinstance(policy.get("exceptions"), list):
        raise ValueError("Invalid vulnerability exception policy")
    fields = ("owner", "reason", "mitigation", "tracking", "accepted_on", "expires_on")
    if any(not isinstance(policy.get(key), str) or not policy[key].strip() for key in fields):
        raise ValueError("Incomplete vulnerability exception assessment")
    start, end = date.fromisoformat(policy["accepted_on"]), date.fromisoformat(policy["expires_on"])
    if start >= end:
        raise ValueError("Invalid vulnerability exception review period")
    exceptions = {}
    for entry in policy["exceptions"]:
        reference = entry.get("image") if isinstance(entry, dict) else None
        if not isinstance(reference, str) or not re.fullmatch(r"[^@\s]+@sha256:[0-9a-f]{64}", reference):
            raise ValueError("Vulnerability exceptions require an immutable image")
        if reference in exceptions:
            raise ValueError("Duplicate vulnerability exception")
        exceptions[reference] = {"image": reference, **{key: policy[key] for key in fields}}
    return exceptions


def apply_vulnerability_exceptions(assessment, reference, exceptions, today=None):
    today = today or datetime.now(UTC).date()
    result = {**assessment, "blocking": [], "accepted": [], "expired_exceptions": []}
    for finding in assessment["blocking"]:
        entry = exceptions.get(reference)
        if entry and date.fromisoformat(entry["accepted_on"]) <= today < date.fromisoformat(entry["expires_on"]):
            result["accepted"].append({**finding, "exception": entry})
        else:
            result["blocking"].append(finding)
            if entry and today >= date.fromisoformat(entry["expires_on"]):
                result["expired_exceptions"].append({**finding, "exception": entry})
    return result


def verify_scan_policy(summary, reports, images, today=None):
    # Publication can occur after scanning. Recheck expiry and current policy.
    policy_hash = checksum(VULNERABILITY_EXCEPTIONS)
    if (summary.get("vulnerability_exceptions_sha256") != policy_hash or
            summary["files"].get(VULNERABILITY_EXCEPTIONS.name) != policy_hash):
        raise ValueError("Vulnerability exception policy changed; rescan the candidate")
    exceptions = load_vulnerability_exceptions()
    targets = [("source", None)] + [(scope, image["immutable"]) for scope, image in image_scopes(images)]
    for scope, reference in targets:
        assessment = assess(json.loads((reports / f"{scope}.json").read_text()), image=reference is not None)
        current = apply_vulnerability_exceptions(assessment, reference, exceptions, today)
        if current["blocking"]:
            raise ValueError(f"Blocking findings or expired vulnerability exceptions: {scope}")


def assess(report, image=False):
    results = report.get("Results") or []
    packages = [package for result in results for package in result.get("Packages") or []]
    if not packages:
        raise ValueError("Missing dependency inventory")
    if image:
        os_info = report.get("Metadata", {}).get("OS") or {}
        if os_info.get("EOSL"):
            raise ValueError("Image OS has reached end of support")
        if os_info and (not os_info.get("Family") or not os_info.get("Name") or not any(
                result.get("Class") == "os-pkgs" and result.get("Packages") for result in results)):
            raise ValueError("Missing image OS package inventory")
        go_packages = [package for result in results if result.get("Type") == "gobinary"
                       for package in result.get("Packages") or []]
        if go_packages and not any(package.get("Name") == "stdlib" and package.get("Version") for package in go_packages):
            raise ValueError("Missing Go standard library inventory")
        # Scratch provider images may contain Go packages without an OS database.
        if not os_info and not any(result.get("Type") == "gobinary" for result in results):
            raise ValueError("Image has neither OS nor Go runtime inventory")
    vulnerabilities = [{**item, "Target": result.get("Target", "")} for result in results
                       for item in result.get("Vulnerabilities") or []]
    blocking = [item for item in vulnerabilities if item["Severity"] == "CRITICAL" or
                item["Severity"] == "HIGH" and (item.get("FixedVersion") or "").strip()]
    deferred = [item for item in vulnerabilities if item["Severity"] == "HIGH" and
                not (item.get("FixedVersion") or "").strip()]
    return {"packages": len(packages), "blocking": blocking, "unfixed_high": deferred}


def write_scan_summary(reports, summary):
    scopes = summary["scopes"]
    labels = {f"external-{index:02d}": (item["declared"].split("@")[0], item["usage"])
              for index, item in enumerate(summary.get("external_components", []))}
    labels["source"] = ("Source dependencies", "source")
    advisory = summary.get("scope") == "test"
    result = "PASS" if summary["passed"] else "REVIEW" if advisory else "FAIL"
    column = "Policy findings" if advisory else "Blocking"
    lines = ["# Security scan", "", "Scope: " + summary.get("scope", "production"), "",
             "Result: **" + result + "**" + (" (advisory; does not block production)" if advisory else ""), "",
             "Counts are package occurrences, not unique vulnerabilities. Accepted findings still need review.", "",
             f"| Image or source | Use | {column} | Accepted | Unfixed HIGH |", "| --- | --- | ---: | ---: | ---: |"]
    for scope, assessment in scopes.items():
        label, usage = labels.get(scope, (scope, "unknown"))
        lines.append(f"| `{label}` | {usage} | {len(assessment['blocking'])} | "
                     f"{len(assessment.get('accepted', []))} | {len(assessment['unfixed_high'])} |")
    totals = [sum(len(value.get(key, [])) for value in scopes.values())
              for key in ("blocking", "accepted", "unfixed_high")]
    lines.append(f"| **Total** | | **{totals[0]}** | **{totals[1]}** | **{totals[2]}** |")
    expiry = sorted({item["exception"]["expires_on"] for assessment in scopes.values()
                     for item in assessment.get("accepted", [])})
    if expiry:
        lines.extend(["", "Exception expiry (UTC): **" + ", ".join(expiry) + "**."])
    if summary["errors"]:
        lines.extend(["", "## Errors", "", *["- " + error for error in summary["errors"]]])
    lines.extend(["", "See scan-summary.json and the scope reports for immutable digests, findings, checksums, and assessment details."])
    (reports / "summary.md").write_text("\n".join(lines) + "\n")


def scan(candidate, reports, allow_dirty=False, scope="production"):
    reports.mkdir(parents=True, exist_ok=False)
    summary = {"passed": False, "manifest_sha256": "", "scope": scope,
               "scopes": {}, "errors": [], "scanned_at": datetime.now(UTC).isoformat()}
    try:
        exceptions = load_vulnerability_exceptions() if scope == "production" else {}
        if scope == "production":
            shutil.copyfile(VULNERABILITY_EXCEPTIONS, reports / VULNERABILITY_EXCEPTIONS.name)
            summary["vulnerability_exceptions_sha256"] = checksum(VULNERABILITY_EXCEPTIONS)
        summary["manifest_sha256"] = checksum(candidate / "security-manifest.json")
        manifest = verify(candidate, allow_dirty=allow_dirty)
        if manifest.get("scope") != scope:
            raise ValueError("Candidate and scan scopes do not match")
        summary.update(version=manifest["version"], commit=manifest["commit"], image_digest=manifest["image_digest"])
        shutil.copyfile(candidate / "security-manifest.json", reports / "security-manifest.json")
        with tempfile.TemporaryDirectory(prefix="datalab-scan-") as temporary:
            source = Path(temporary) / "source"
            unpack_source(candidate / "source.tar.gz", source)
            check_package(candidate / "datalab.xpkg", source)
            images = json.loads((candidate / "external-components.json").read_text())
            runtime = set(external_images(source, "production"))
            if ({item["declared"] for item in images} != set(external_images(source, scope)) or
                    any(item.get("usage") != ("runtime" if item["declared"] in runtime else "test") for item in images)):
                raise ValueError("External image inventory does not match source usage")
            summary["external_components"] = images
            shutil.copyfile(candidate / "external-components.json", reports / "external-components.json")
            locks = LOCKFILES if scope == "production" else TEST_LOCKFILES
            source_args = (["fs", "--skip-dirs", str(source / "tests"), str(source)] if scope == "production"
                           else ["fs", str(source / "tests")])
            targets = [("source", source_args, None)] + [
                (label, ["image", "--image-src", "remote", "--platform", "linux/amd64", item["immutable"]], item["immutable"])
                for label, item in image_scopes(images, scope)]
            for label, arguments, reference in targets:
                try:
                    report = reports / f"{label}.json"
                    print(f"Scanning {label}", flush=True)
                    scan_command([tool("trivy"), *arguments, "--config", "/dev/null", "--ignorefile", "/dev/null",
                         "--cache-dir", ROOT / "build/trivy-cache", "--no-progress",
                         "--scanners", "vuln", "--list-all-pkgs",
                         "--format", "json", "--output", report, "--exit-code", "0", "--timeout", "15m"],
                         reports / f"{label}.log")
                    data = json.loads(report.read_text())
                    run([tool("trivy"), "convert", "--format", "cyclonedx", "--output",
                         reports / f"{label}.cdx.json", report])
                    sbom = json.loads((reports / f"{label}.cdx.json").read_text())
                    if sbom.get("bomFormat") != "CycloneDX" or not sbom.get("components"):
                        raise ValueError("Missing CycloneDX dependency inventory")
                    sbom.setdefault("metadata", {}).setdefault("properties", []).extend([
                        {"name": "versioneer.at/source-commit", "value": manifest["commit"]},
                        {"name": "versioneer.at/manifest-sha256", "value": summary["manifest_sha256"]},
                        {"name": "versioneer.at/scan-scope", "value": label},
                    ])
                    write_json(reports / f"{label}.cdx.json", sbom)
                    assessment = apply_vulnerability_exceptions(
                        assess(data, image=reference is not None), reference, exceptions)
                    if label == "source":
                        inventories = locks if scope == "production" else (*locks, "tests/admission/go.mod")
                        for name in inventories:
                            suffix = name if scope == "production" else name.removeprefix("tests/")
                            if not any(item.get("Target", "").endswith(suffix) and item.get("Packages")
                                       for item in data.get("Results", [])):
                                raise ValueError(f"Missing source dependency inventory: {name}")
                    summary["scopes"][label] = assessment
                except (ValueError, OSError, subprocess.CalledProcessError) as error:
                    summary["errors"].append(f"{label}: {error}")
            if scope == "production" and check_secrets(source, reports):
                summary["errors"].append("Unresolved secret findings or scanner error")
            if scope == "test":
                with (reports / "go.log").open("w") as output:
                    # JSON mode returns zero even when it finds affected code.
                    result = subprocess.run(
                        [str(tool("govulncheck")), "-show", "verbose", "./..."],
                        cwd=source / "tests/admission", stdout=output, stderr=subprocess.STDOUT,
                    )
                if result.returncode:
                    summary["errors"].append("Go check failed; see go.log")
            for name in locks:
                label = name.replace("/", "-")
                result = subprocess.run([sys.executable, "-m", "pip_audit", "--disable-pip", "--require-hashes",
                                         "--cache-dir", str(ROOT / "build/pip-audit-cache"),
                                         "-r", str(source / name), "--format", "json", "--output", str(reports / f"{label}.json")],
                                        stdout=subprocess.DEVNULL)
                if result.returncode:
                    summary["errors"].append(f"Python audit failed: {name}")
        summary["scanner"] = json.loads(run([tool("trivy"), "--cache-dir", ROOT / "build/trivy-cache", "--version", "--format", "json"],
                                           capture_output=True, text=True).stdout)
        summary["tools"] = {name: spec["version"] for name, spec in
                            json.loads((ROOT / "scripts/tools.json").read_text()).items()}
        summary["pip_audit"] = run([sys.executable, "-m", "pip_audit", "--version"], capture_output=True, text=True).stdout.strip()
        summary["passed"] = not summary["errors"] and not any(
            value["blocking"] for value in summary["scopes"].values())
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        summary["errors"].append(str(error))
    finally:
        write_scan_summary(reports, summary)
        summary["files"] = {path.name: checksum(path) for path in sorted(reports.iterdir())
                            if path.is_file() and path.name != "scan-summary.json"}
        write_json(reports / "scan-summary.json", summary)
    print(json.dumps({"passed": summary["passed"], "errors": summary["errors"],
                      "blocking": {name: len(value["blocking"]) for name, value in summary["scopes"].items()},
                      "accepted": {name: len(value["accepted"]) for name, value in summary["scopes"].items()}}))
    return 0 if summary["passed"] else 1


def check_files(source, reports):
    reports.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix="datalab-files-") as temporary:
        snapshot = Path(temporary)
        for path in source_paths(source):
            target = snapshot / path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / path, target)
        return check_secrets(snapshot, reports)


def secret_is_fixture(finding, source, exceptions):
    relative = Path(finding["File"]).relative_to(source)
    rule = exceptions.get(relative.as_posix(), {})
    return (finding["RuleID"] in rule.get("rules", []) and
            rule.get("sha256") == checksum(source / relative))


def check_secrets(source, reports):
    result = subprocess.run([str(tool("gitleaks")), "dir", str(source), "--redact", "--report-format", "json",
                             "--report-path", str(reports / "secrets.json")])
    if result.returncode not in (0, 1) or not (reports / "secrets.json").is_file():
        return 1
    exceptions = json.loads((source / "scripts/secret-fixtures.json").read_text())
    findings = json.loads((reports / "secrets.json").read_text())
    unresolved = [finding for finding in findings if not secret_is_fixture(finding, source, exceptions)]
    write_json(reports / "secret-assessment.json", {"unresolved": len(unresolved),
               "reviewed_fixture_matches": len(findings) - len(unresolved)})
    print(f"Secret scan: {len(unresolved)} unresolved matches; {len(findings) - len(unresolved)} reviewed fixture matches")
    return 1 if unresolved else 0


def select_releases(releases, tags="", published_tags=()):
    drafts = {item["tag_name"] for item in releases if item.get("draft")}
    releases = [item for item in releases if not item.get("draft") and VERSION.fullmatch(item["tag_name"])]
    by_tag = {item["tag_name"]: item for item in releases}
    for tag in published_tags:
        if tag not in drafts and VERSION.fullmatch(tag):
            by_tag.setdefault(tag, {"tag_name": tag, "prerelease": "-" in tag})
    if tags.strip():
        selected = list(dict.fromkeys(tag.strip() for tag in tags.split(",")))
        if any(tag not in by_tag for tag in selected):
            raise ValueError("Unknown or unpublished release tag")
    else:
        def base(tag):
            return tuple(map(int, VERSION.fullmatch(tag).groups()[:3]))
        supported = [tag for tag in by_tag if base(tag)[:2] != (0, 12)]
        stable = [tag for tag in by_tag if "-" not in tag and not by_tag[tag].get("prerelease")]
        latest = max(stable, key=base) if stable else None
        selected = [latest] if latest in supported else []
        candidates = [tag for tag in supported if "-rc." in tag and
                      (not latest or base(tag) > base(latest))]
        if candidates:
            selected.append(max(candidates, key=lambda tag: (*base(tag), int(tag.rsplit(".", 1)[1]))))
    if not selected:
        raise ValueError("No published release evidence exists; publish a release before scheduled scans")
    return {"include": [{"tag": tag} for tag in selected]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare_parser = sub.add_parser("prepare")
    prepare_parser.add_argument("--source", type=Path, default=ROOT)
    prepare_parser.add_argument("--version", required=True)
    prepare_parser.add_argument("--commit", required=True)
    for name in ("prepare", "scan", "verify"):
        child = prepare_parser if name == "prepare" else sub.add_parser(name)
        child.add_argument("--candidate", type=Path, default=ROOT / "build/candidate")
        child.add_argument("--allow-dirty", action="store_true")
        if name != "prepare":
            child.add_argument("--reports", type=Path, default=ROOT / "build/security")
        if name in {"prepare", "scan"}:
            child.add_argument("--scope", choices=("production", "test"), default="production")
    releases = sub.add_parser("releases")
    releases.add_argument("--tags", default="")
    releases.add_argument("--published-tags-file", type=Path)
    files = sub.add_parser("files")
    files.add_argument("--source", type=Path, default=ROOT)
    files.add_argument("--reports", type=Path, default=ROOT / "build/file-security")
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.source.resolve(), args.candidate.resolve(), args.version, args.commit, args.allow_dirty, args.scope)
    elif args.command == "scan":
        return scan(args.candidate.resolve(), args.reports.resolve(), args.allow_dirty, args.scope)
    elif args.command == "verify":
        verify(args.candidate.resolve(), args.reports.resolve(), allow_dirty=args.allow_dirty)
    elif args.command == "files":
        return check_files(args.source.resolve(), args.reports.resolve())
    else:
        data = json.load(sys.stdin)
        if data and isinstance(data[0], list):
            data = [item for page in data for item in page]
        published = args.published_tags_file.read_text().splitlines() if args.published_tags_file else []
        print(json.dumps(select_releases(data, args.tags, published)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
