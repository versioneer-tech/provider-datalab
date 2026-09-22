#!/usr/bin/env bash
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

INTEGRATION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.bash
source "${INTEGRATION_DIR}/lib.bash"

require_command docker
require_command kind
require_command kubectl

if kind_cluster_exists; then
  export_kind_kubeconfig
  printf 'Reusing kind cluster %s with context %s.\n' \
    "${KIND_CLUSTER_NAME}" "${KUBECTL_CONTEXT}"
  kube cluster-info
  exit 0
fi

if ! docker info >/dev/null 2>&1; then
  printf 'Docker is not available. Start Docker before creating the cluster.\n' >&2
  exit 1
fi

log "Creating dedicated kind cluster ${KIND_CLUSTER_NAME}"
KUBECONFIG="${PROVIDER_DATALAB_KUBECONFIG}" \
  kind create cluster \
    --name "${KIND_CLUSTER_NAME}" \
    --config "${MANIFEST_DIR}/kind.yaml" \
    --wait 5m
kube cluster-info

printf 'Remove this test cluster when the validation cycle is complete:\n'
printf 'KUBECONFIG=%s kind delete cluster --name %s\n' \
  "${PROVIDER_DATALAB_KUBECONFIG}" "${KIND_CLUSTER_NAME}"

