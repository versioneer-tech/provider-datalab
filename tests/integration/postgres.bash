#!/usr/bin/env bash
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

install_cnpg() {
  local namespace=cnpg-system
  require_command helm
  log 'Installing the checked CloudNativePG chart'
  local chart
  chart="$(python3 "${REPO_ROOT}/scripts/components.py" cnpg-chart)"
  # CNPG includes CRDs as chart templates, so Helm creates and updates them.
  helm_it upgrade --install cnpg "${chart}" \
    --kubeconfig "${PROVIDER_DATALAB_KUBECONFIG}" \
    --kube-context "${KUBECTL_CONTEXT}" \
    --namespace "${namespace}" --create-namespace \
    --post-renderer "${REPO_ROOT}/scripts/components.py" \
    --set fullnameOverride=cnpg \
    --set resources.requests.cpu=100m \
    --set resources.requests.memory=128Mi \
    --set resources.limits.cpu=500m \
    --set resources.limits.memory=512Mi \
    --wait --timeout 10m
  start_operator "${namespace}" cnpg
}
