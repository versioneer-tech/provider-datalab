#!/usr/bin/env bash
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

INTEGRATION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.bash
source "${INTEGRATION_DIR}/lib.bash"

profile="$(selected_profile "${1:-}" "$0")"

"${INTEGRATION_DIR}/create-cluster.bash"
"${INTEGRATION_DIR}/deploy-platform.bash" "${profile}"
"${INTEGRATION_DIR}/deploy-storages.bash" minio

if [[ "${profile}" == complex ]]; then
  "${INTEGRATION_DIR}/deploy-storages.bash" aws
  "${INTEGRATION_DIR}/deploy-storages.bash" ovh
  printf '\nMinIO, AWS, and OVHcloud storage integration is ready.\n'
elif [[ "${profile}" == verify-network ]]; then
  "${INTEGRATION_DIR}/verify-network.bash"
  printf '\nMinIO storage and network-policy verification are ready.\n'
else
  printf '\nMinIO storage integration for Jeff and Jane is ready.\n'
fi
