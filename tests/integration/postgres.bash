#!/usr/bin/env bash
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

: "${CNPG_CHART_VERSION:=0.29.2}"

install_cnpg() {
  local namespace=cnpg-system
  require_command helm
  if helm_release_matches cnpg "${namespace}" "cloudnative-pg-${CNPG_CHART_VERSION}"; then
    start_operator "${namespace}" cnpg
    return
  fi
  log "Installing CloudNativePG chart ${CNPG_CHART_VERSION}"
  helm_it repo add cnpg https://cloudnative-pg.github.io/charts --force-update
  helm_it repo update cnpg
  # CNPG includes CRDs as chart templates, so Helm creates and updates them.
  helm_it upgrade --install cnpg cnpg/cloudnative-pg \
    --kubeconfig "${PROVIDER_DATALAB_KUBECONFIG}" \
    --kube-context "${KUBECTL_CONTEXT}" \
    --namespace "${namespace}" --create-namespace \
    --version "${CNPG_CHART_VERSION}" \
    --set fullnameOverride=cnpg \
    --set resources.requests.cpu=100m \
    --set resources.requests.memory=128Mi \
    --set resources.limits.cpu=500m \
    --set resources.limits.memory=512Mi \
    --wait --timeout 10m
  start_operator "${namespace}" cnpg
}
