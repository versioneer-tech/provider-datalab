#!/usr/bin/env python3
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Report newer image tags and changed tag digests without changing source."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
import json
from pathlib import Path
import re
import runpy
import subprocess
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SECURITY = runpy.run_path(str(ROOT / "scripts/security.py"))
VERSION = re.compile(r"(vnext\.|v?)([0-9]+(?:\.[0-9]+){1,2})(.*)")
POSTGIS = re.compile(r"([0-9]+)\.([0-9]+)-([0-9]+)\.([0-9]+)\.([0-9]+)-([0-9]{12})-(.+)")


def version_family(tag):
    dated = POSTGIS.fullmatch(tag)
    if dated:
        return ("postgis", dated[7]), tuple(int(dated[index]) for index in range(1, 7))
    match = VERSION.fullmatch(tag)
    if not match:
        return None
    parts = tuple(int(part) for part in match[2].split("."))
    # Keep image variants separate and exclude prerelease tags from stable updates.
    if re.match(r"[-.]?(?:alpha|beta|rc|dev|canary|nightly)(?:[.0-9-]|$)", match[3]):
        return None
    return (match[1], match[3], len(parts)), parts


def newer_tags(current, tags):
    family = version_family(current)
    if family is None:
        return {}
    result = {}
    for tag in tags:
        candidate = version_family(tag)
        if candidate is None or candidate[0] != family[0] or candidate[1] <= family[1]:
            continue
        before, after = family[1], candidate[1]
        major_change = before[0] != after[0] or family[0][0] == "postgis" and before[2] != after[2]
        kind = "major" if major_change else "minor" if before[1] != after[1] else "patch_or_rebuild"
        if kind not in result or candidate[1] > version_family(result[kind])[1]:
            result[kind] = tag
    return result


def crane(*arguments):
    command = [str(ROOT / "build/tools/crane"), *arguments]
    for attempt in range(3):
        try:
            return subprocess.run(command, capture_output=True, text=True, check=True, timeout=30).stdout.strip()
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            if attempt == 2:
                raise
            time.sleep(attempt + 1)


def check_reference(reference):
    tagged, _, pinned = reference.partition("@")
    repository, separator, tag = tagged.rpartition(":")
    if not separator or not tag or "/" in tag:
        raise ValueError("An explicit image tag is required")
    current = crane("digest", tagged)
    if not SECURITY["DIGEST"].fullmatch(current):
        raise ValueError("The registry did not return an image digest")
    family = version_family(tag)
    return {"reference": reference, "current_digest": current, "pinned": bool(pinned),
            "digest_changed": bool(pinned and pinned != current),
            "newer_tags": newer_tags(tag, crane("ls", repository).splitlines()) if family else {},
            "version_check": "version_family" if family else "same_tag_digest_only"}


def check_all(references, check=check_reference):
    def inspect(reference):
        try:
            return check(reference)
        except (ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            return {"reference": reference, "error": str(error)}
    with ThreadPoolExecutor(max_workers=2) as executor:
        return list(executor.map(inspect, references))


def test_package_updates(source):
    from packaging.requirements import Requirement
    from packaging.version import Version

    results = []
    for lock in SECURITY["TEST_LOCKFILES"]:
        versions = dict(re.findall(r"(?m)^([\w.-]+)==([^\s;]+)", (source / lock).read_text()))
        for line in (source / lock).with_suffix(".in").read_text().splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            requirement = Requirement(line)
            name = requirement.name
            current = next(value for key, value in versions.items() if key.lower() == name.lower())
            item = {"manifest": lock, "package": name, "current": current}
            try:
                with urllib.request.urlopen(f"https://pypi.org/pypi/{name}/json", timeout=30) as response:
                    latest = json.load(response)["info"]["version"]
                version = Version(latest)
                item.update(latest=latest, update_available=version > Version(current)
                            and not version.is_prerelease and not version.is_devrelease)
            except (OSError, ValueError, KeyError) as error:
                item["error"] = str(error)
            results.append(item)
    try:
        output = subprocess.run(["go", "list", "-m", "-u", "-mod=readonly", "-f",
            "{{if .Update}}{{.Path}} {{.Version}} {{.Update.Version}}{{end}}", "all"],
            cwd=source / "tests/admission", check=True, capture_output=True, text=True, timeout=180).stdout
        for line in output.splitlines():
            if not line.strip():
                continue
            name, current, latest = line.split()
            results.append({"manifest": "tests/admission/go.mod", "package": name,
                            "current": current, "latest": latest, "update_available": True})
    except (OSError, ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        detail = error.stderr.strip() if isinstance(error, subprocess.CalledProcessError) and error.stderr else str(error)
        results.append({"manifest": "tests/admission/go.mod", "package": "Go modules", "error": detail})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT)
    parser.add_argument("--reports", type=Path, default=ROOT / "build/image-updates")
    parser.add_argument("--scope", choices=("production", "test"), default="production")
    args = parser.parse_args()
    references = SECURITY["external_images"](args.source, args.scope)
    results = check_all(references)
    packages = test_package_updates(args.source) if args.scope == "test" else []
    errors = sum("error" in item for item in [*results, *packages])
    args.reports.mkdir(parents=True, exist_ok=False)
    (args.reports / "updates.json").write_text(json.dumps(
        {"checked_at": datetime.now(UTC).isoformat(), "scope": args.scope,
         "errors": errors, "images": results, "packages": packages}, indent=2) + "\n")
    lines = ["# Image update check", "", "Registry metadata only; replacement images still need scans and tests.",
             "", "| Image | Result |", "| --- | --- |"]
    for item in results:
        if "error" in item:
            status = "Registry lookup failed; see updates.json"
        else:
            changes = [f"{kind}: {tag}" for kind, tag in item["newer_tags"].items()]
            if item["digest_changed"]:
                changes.insert(0, "Current tag has a new digest")
            if not item["pinned"]:
                changes.append("Source reference is not pinned")
            if item["version_check"] == "same_tag_digest_only":
                changes.append("Tag digest checked; version comparison unavailable")
            status = "; ".join(changes) or "No update found"
        lines.append(f"| `{item['reference']}` | {status} |")
    if packages:
        lines.extend(["", "## Test package updates", "",
                      "Direct Python dependencies and available Go module updates. Transitive Python dependencies are audited in the scan.",
                      "Latest versions can be outside current constraints. Review changes before updating locks.", "",
                      "| Manifest | Package | Locked | Latest |", "| --- | --- | --- | --- |"])
        for item in packages:
            latest = "Lookup failed; see updates.json" if "error" in item else item["latest"]
            lines.append(f"| `{item['manifest']}` | `{item['package']}` | {item.get('current', '')} | {latest} |")
    summary = "\n".join(lines) + "\n"
    (args.reports / "summary.md").write_text(summary)
    print(summary)
    return bool(errors)


if __name__ == "__main__":
    raise SystemExit(main())
