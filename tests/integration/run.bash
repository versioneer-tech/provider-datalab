#!/usr/bin/env bash
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

INTEGRATION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.bash
source "${INTEGRATION_DIR}/lib.bash"

if [[ "${1:-}" == all ]]; then
  profiles=(verify-network verify-registry verify-data verify-s3 verify-postgres verify-mongo verify-redis verify-qdrant)
else
  profiles=("$(selected_profile "${1:-}" "$0")")
fi

started=${SECONDS}
"${INTEGRATION_DIR}/create-cluster.bash"
"${INTEGRATION_DIR}/deploy-platform.bash"
if [[ "${1:-}" == all ]]; then
  kube apply -f "${MANIFEST_DIR}/s3/keycloak.yaml"
fi
printf 'Platform setup passed in %s seconds.\n' "$((SECONDS - started))"

for profile in "${profiles[@]}"; do
  started=${SECONDS}
  "${INTEGRATION_DIR}/${profile}.bash"
  printf '\nIntegration profile %s passed in %s seconds.\n' "${profile}" "$((SECONDS - started))"
done
