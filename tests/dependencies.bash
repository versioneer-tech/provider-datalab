#!/usr/bin/env bash
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

for tool in trivy govulncheck; do
  [[ -x "build/tools/${tool}" ]] || { printf 'Install the test scan tool: %s\n' "${tool}" >&2; exit 1; }
done
python3 -c 'import pip_audit, packaging'
mkdir -p build/test-dependencies
reports="$(mktemp -d "$PWD/build/test-dependencies/run.XXXXXX")"
printf 'Test dependency reports: %s\n' "${reports}"
python3 scripts/security.py prepare --scope test --version 0.0.0-rc.1 --commit "$(git rev-parse HEAD)" \
  --candidate "${reports}/candidate" --allow-dirty

# Test-only findings need review but do not approve or block production releases.
result=0
python3 scripts/check-image-updates.py --scope test --reports "${reports}/updates" || result=1
python3 scripts/security.py scan --scope test --candidate "${reports}/candidate" \
  --reports "${reports}/security" --allow-dirty || result=1
if ((result)); then
  printf 'Review test dependency findings or check failures in %s before using the fixtures.\n' "${reports}"
fi
