#!/usr/bin/env python3
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Select the documentation checks or the full test suite."""

import argparse
import subprocess


def documentation_only(paths):
    return bool(paths) and all(
        path.endswith(".md") or path.startswith("docs/") or path == "mkdocs.yml"
        for path in paths
    )


def git(*arguments):
    return subprocess.run(
        ["git", *arguments], check=True, capture_output=True,
    ).stdout


def select_checks(base, head=None):
    if not base:
        return False
    try:
        refs = [base] if head is None else [base, head]
        revisions = [
            git("rev-parse", "--verify", "--end-of-options", ref + "^{commit}").decode().strip()
            for ref in refs
        ]
        # Include both paths of a rename so moved runtime files still require tests.
        changed = git("diff", "--name-only", "--no-renames", "-z", *revisions, "--")
        if head is None:
            changed += git("ls-files", "--others", "--exclude-standard", "-z")
    except subprocess.CalledProcessError:
        return False
    paths = changed.decode("utf-8", "surrogateescape").split("\0")
    return documentation_only([path for path in paths if path])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", help="Base commit or target branch; missing refs select all checks.")
    parser.add_argument("--head", help="Head commit; omit to include staged, unstaged, and untracked files.")
    args = parser.parse_args()
    print("docs_only=" + str(select_checks(args.base, args.head)).lower())


if __name__ == "__main__":
    main()
