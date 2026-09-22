#!/usr/bin/env bash
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

INTEGRATION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.bash
source "${INTEGRATION_DIR}/lib.bash"

profile="$(selected_profile "${1:-}" "$0")"

"${INTEGRATION_DIR}/create-cluster.bash"
"${INTEGRATION_DIR}/deploy-platform.bash"

"${INTEGRATION_DIR}/${profile}.bash"
printf '\nIntegration profile %s passed.\n' "${profile}"
