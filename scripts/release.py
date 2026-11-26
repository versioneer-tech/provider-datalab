#!/usr/bin/env python3
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Check release qualification and download published scan inputs."""

import argparse
import importlib.util
import json
import subprocess
import tarfile
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("release_security", Path(__file__).with_name("security.py"))
SECURITY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SECURITY)


def api(path):
    return json.loads(SECURITY.run(["gh", "api", path], capture_output=True, text=True).stdout)


def qualified_run(run, commit, branch, jobs):
    expected = {"changes", "documentation", "runtime_checks", "security_checks", "required_checks"}
    by_name = {job["name"]: job for job in jobs}
    return (run["head_sha"] == commit and run["head_branch"] == branch and
            run["event"] in {"push", "workflow_dispatch"} and run["conclusion"] == "success" and
            expected <= by_name.keys() and all(by_name[name]["conclusion"] == "success" for name in expected))


def advances_latest(tag, releases):
    if "-" in tag:
        return False
    versions = [tuple(map(int, item["tag_name"].split("."))) for item in releases
                if not item.get("draft") and not item.get("prerelease") and
                SECURITY.VERSION.fullmatch(item["tag_name"]) and "-" not in item["tag_name"]]
    return not versions or tuple(map(int, tag.split("."))) >= max(versions)


def qualify(repository, commit):
    branch = api(f"repos/{repository}")["default_branch"]
    info = api(f"repos/{repository}/branches/{branch}")
    if not info["protected"]:
        raise ValueError("The default branch is not protected")
    data = api(f"repos/{repository}/actions/workflows/pr.yaml/runs?head_sha={commit}&per_page=100")
    for workflow in data["workflow_runs"]:
        if workflow["head_branch"] != branch:
            continue
        jobs = []
        page = 1
        while True:
            batch = api(f"repos/{repository}/actions/runs/{workflow['id']}/attempts/{workflow['run_attempt']}/jobs?per_page=100&page={page}")["jobs"]
            jobs.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        if qualified_run(workflow, commit, branch, jobs):
            print(f"release_branch={branch}")
            print(f"tests_run_id={workflow['id']}")
            return
    raise ValueError("The release commit needs a successful full default-branch Tests run")


def download(repository, tag, destination):
    if not SECURITY.VERSION.fullmatch(tag):
        raise ValueError("Invalid release tag")
    release = api(f"repos/{repository}/releases/tags/{tag}")
    if release["draft"]:
        raise ValueError("Draft releases cannot be scanned")
    destination.mkdir(parents=True, exist_ok=False)
    names = ("security-manifest.json", "datalab.xpkg", "source.tar.gz", "package.cdx.json", "external-components.json")
    for name in names:
        SECURITY.run(["gh", "release", "download", tag, "--repo", repository, "--pattern", name, "--dir", destination])
    manifest = SECURITY.verify(destination, version=tag)
    reference = manifest["image"] + "@" + manifest["image_digest"]
    actual = SECURITY.run([SECURITY.tool("crane"), "digest", reference], capture_output=True, text=True).stdout.strip()
    if actual != manifest["image_digest"]:
        raise ValueError("Published package digest does not match")


def publish(repository, candidate, reports, tag, commit, candidate_id, reports_id, run_id):
    manifest = SECURITY.verify(candidate, reports, version=tag, commit=commit)
    reference = manifest["image"] + ":" + tag
    # Refuse to replace an existing tag with other bytes after a partial run.
    existing = subprocess.run([str(SECURITY.tool("crane")), "digest", reference], capture_output=True, text=True)
    if existing.returncode == 0 and existing.stdout.strip() != manifest["image_digest"]:
        raise ValueError("The published tag already identifies another package")
    if existing.returncode:
        if not any(word in existing.stderr for word in ("MANIFEST_UNKNOWN", "NAME_UNKNOWN")):
            raise ValueError("Cannot establish whether the publication tag exists")
        SECURITY.run([SECURITY.tool("crane"), "push", candidate / "datalab.xpkg", reference])
    actual = SECURITY.run([SECURITY.tool("crane"), "digest", reference], capture_output=True, text=True).stdout.strip()
    if actual != manifest["image_digest"]:
        raise ValueError("Registry did not preserve the checked package manifest")
    with tarfile.open(candidate / "scan-records.tar.gz", "w:gz") as bundle:
        bundle.add(reports, arcname="scan-records")
    inventories = sorted(reports.glob("*.cdx.json"))
    SECURITY.write_json(candidate / "publication.json", {
        "repository": repository, "commit": commit, "image_digest": manifest["image_digest"],
        "candidate_artifact_id": candidate_id, "reports_artifact_id": reports_id,
        "workflow_run_id": run_id,
    })
    assets = [candidate / name for name in (*manifest["files"], "security-manifest.json", "scan-records.tar.gz")]
    assets.append(candidate / "publication.json")
    assets.extend(inventories)
    checksums = candidate / "release-checksums.txt"
    checksums.write_text("".join(f"{SECURITY.checksum(path)}  {path.name}\n" for path in assets))
    assets.append(checksums)
    pages = json.loads(SECURITY.run(["gh", "api", "--paginate", "--slurp", f"repos/{repository}/releases"],
                                   capture_output=True, text=True).stdout)
    latest = advances_latest(tag, [item for page in pages for item in page])
    SECURITY.run(["gh", "release", "create", tag, "--repo", repository, "--verify-tag", "--generate-notes",
                  "--latest=" + str(latest).lower(), *(["--prerelease"] if "-" in tag else []),
                  *assets])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("qualify", "download", "publish"):
        child = sub.add_parser(name)
        child.add_argument("--repository", required=True)
        if name != "download":
            child.add_argument("--commit", required=True)
        if name != "qualify":
            child.add_argument("--tag", required=True)
            child.add_argument("--candidate", type=Path, default=Path("build/candidate"))
        if name == "publish":
            child.add_argument("--reports", type=Path, default=Path("build/security"))
            child.add_argument("--candidate-id", type=int, required=True)
            child.add_argument("--reports-id", type=int, required=True)
            child.add_argument("--run-id", type=int, required=True)
    args = parser.parse_args()
    if args.command == "qualify":
        qualify(args.repository, args.commit)
    elif args.command == "download":
        try:
            download(args.repository, args.tag, args.candidate.resolve())
        except (ValueError, OSError, subprocess.CalledProcessError) as error:
            SECURITY.write_json(Path("build/security/scan-summary.json"), {
                "passed": False, "release_tag": args.tag, "errors": [str(error)],
            })
            raise
    else:
        publish(args.repository, args.candidate.resolve(), args.reports.resolve(), args.tag, args.commit,
                args.candidate_id, args.reports_id, args.run_id)


if __name__ == "__main__":
    main()
