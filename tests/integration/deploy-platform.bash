#!/usr/bin/env bash
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

INTEGRATION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.bash
source "${INTEGRATION_DIR}/lib.bash"

install_crossplane() {
  require_command helm
  log "Installing Crossplane ${CROSSPLANE_VERSION}"
  helm_it repo add crossplane-stable https://charts.crossplane.io/stable --force-update
  helm_it repo update crossplane-stable
  helm_it upgrade --install crossplane crossplane-stable/crossplane \
    --kubeconfig "${PROVIDER_DATALAB_KUBECONFIG}" \
    --kube-context "${KUBECTL_CONTEXT}" \
    --namespace "${CROSSPLANE_NAMESPACE}" \
    --create-namespace \
    --version "${CROSSPLANE_VERSION}" \
    --set 'provider.defaultActivations={}' \
    --wait \
    --timeout 10m
}

install_datalab() {
  log 'Installing Provider Datalab dependencies and source manifests'
  kube apply -f "${REPO_ROOT}/educates/dependencies/00-mrap.yaml"
  kube apply -f "${REPO_ROOT}/educates/dependencies/01-deploymentRuntimeConfigs.yaml"
  kube apply -f "${REPO_ROOT}/educates/dependencies/02-providers.yaml"
  kube apply -f "${REPO_ROOT}/educates/dependencies/functions.yaml"
  kube apply -f "${REPO_ROOT}/educates/dependencies/rbac.yaml"
  wait_for_provider_runtime provider-keycloak
  wait_for_provider_runtime provider-kubernetes
  wait_for_provider_runtime provider-helm
  kube apply -f "${REPO_ROOT}/educates/dependencies/03-providerConfigs.yaml"
  kube apply -f "${REPO_ROOT}/xrd.yaml"
  wait_for_crd_established datalabs.pkg.internal
  kube apply -f "${REPO_ROOT}/educates/composition.yaml"
  kube apply -f "${MANIFEST_DIR}/environment-configs/datalabs.yaml"
}

wait_for_packages() {
  local name
  local -a providers=(
    provider-kubernetes
    provider-keycloak
    provider-helm
  )

  for name in "${providers[@]}"; do
    wait_for_provider_runtime "${name}"
  done
  for name in \
    crossplane-contrib-function-python \
    crossplane-contrib-function-auto-ready; do
    kube wait "function.pkg.crossplane.io/${name}" \
      --for=condition=Healthy --timeout=15m
  done
}

main() {
  require_cluster

  kube apply -f "${MANIFEST_DIR}/namespaces.yaml"
  install_crossplane
  install_datalab
  kube apply -f "${MANIFEST_DIR}/provider-configs/kubernetes.yaml"

  kube apply -f "${MANIFEST_DIR}/minio.yaml"
  kube apply -f "${MANIFEST_DIR}/storage-secrets.yaml"
  kube rollout status deployment/default --namespace minio --timeout=5m
  wait_for_packages
  kube get providers.pkg.crossplane.io,functions.pkg.crossplane.io
}

main "$@"
