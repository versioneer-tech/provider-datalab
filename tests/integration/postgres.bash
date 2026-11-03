#!/usr/bin/env bash
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

: "${PGO_VERSION:=6.0.2}"

install_pgo() {
  local namespace=postgres-operator
  require_command helm
  if helm_release_matches pgo "${namespace}" "pgo-${PGO_VERSION}"; then
    start_operator "${namespace}" pgo
    return
  fi
  log "Installing Crunchy PGO ${PGO_VERSION}"
  apply_operator_crds oci://registry.developers.crunchydata.com/crunchydata/pgo "${PGO_VERSION}"
  helm_it upgrade --install pgo \
    oci://registry.developers.crunchydata.com/crunchydata/pgo \
    --kubeconfig "${PROVIDER_DATALAB_KUBECONFIG}" \
    --kube-context "${KUBECTL_CONTEXT}" \
    --namespace "${namespace}" \
    --create-namespace \
    --version "${PGO_VERSION}" \
    --set singleNamespace=false \
    --wait \
    --timeout 10m
  start_operator "${namespace}" pgo
}

