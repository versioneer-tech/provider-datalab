#!/usr/bin/env bash
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

# Keep each run's reports, including failed secret checks.
reports="${1:-build/file-security/$(date -u +%Y%m%dT%H%M%SZ)-$$}"
printf 'File security reports: %s\n' "${reports}"
python3 tests/ci-checks.py
build/tools/actionlint -shellcheck=
python3 scripts/security.py files --reports "${reports}"
mkdocs build --strict --site-dir build/docs-check
pre-commit run --all-files
git diff --check
