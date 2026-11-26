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
    return {"reference": reference, "current_digest": current, "pinned": bool(pinned),
            "digest_changed": bool(pinned and pinned != current),
            "newer_tags": newer_tags(tag, crane("ls", repository).splitlines()),
            "version_check": "version_family" if version_family(tag) else "same_tag_digest_only"}


def check_all(references, check=check_reference):
    def inspect(reference):
        try:
            return check(reference)
        except (ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            return {"reference": reference, "error": str(error)}
    with ThreadPoolExecutor(max_workers=2) as executor:
        return list(executor.map(inspect, references))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT)
    parser.add_argument("--reports", type=Path, default=ROOT / "build/image-updates")
    args = parser.parse_args()
    references = SECURITY["external_images"](args.source)
    results = check_all(references)
    errors = sum("error" in item for item in results)
    args.reports.mkdir(parents=True, exist_ok=False)
    (args.reports / "updates.json").write_text(json.dumps(
        {"checked_at": datetime.now(UTC).isoformat(), "errors": errors, "images": results}, indent=2) + "\n")
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
            status = "; ".join(changes) or "No update found"
        lines.append(f"| `{item['reference']}` | {status} |")
    summary = "\n".join(lines) + "\n"
    (args.reports / "summary.md").write_text(summary)
    print(summary)
    return bool(errors)


if __name__ == "__main__":
    raise SystemExit(main())
