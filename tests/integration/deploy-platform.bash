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

install_storage_dependencies() {
  local profile="$1"
  local backend manifest
  local -a backends=(minio)

  if [[ "${profile}" == complex ]]; then
    backends+=(aws ovh)
  fi

  log "Installing Provider Storage ${PROVIDER_STORAGE_VERSION} dependencies"
  for backend in "${backends[@]}"; do
    for manifest in \
      dependencies/00-mrap.yaml \
      dependencies/01-deploymentRuntimeConfigs.yaml \
      dependencies/02-providers.yaml \
      dependencies/functions.yaml \
      dependencies/rbac.yaml; do
      apply_storage_manifest "${backend}/${manifest}"
    done
  done
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

install_storage_configurations() {
  local profile="$1"

  log "Installing Provider Storage configuration ${PROVIDER_STORAGE_VERSION}"
  apply_template \
    "${MANIFEST_DIR}/provider-storage-configurations.yaml" \
    PROVIDER_STORAGE_VERSION "${PROVIDER_STORAGE_VERSION}"
  kube wait configuration.pkg.crossplane.io/provider-storage-minio \
    --for=condition=Healthy --timeout=10m
  wait_for_crd_established storages.pkg.internal

  if [[ "${profile}" == complex ]]; then
    # Each backend package contains the same Storage XRD. Install MinIO as the
    # single API owner, then add the AWS and OVHcloud compositions from the
    # same immutable Git tag. Separate backend packages cannot own the XRD
    # together.
    apply_storage_manifest aws/composition.yaml
    apply_storage_manifest ovh/composition.yaml
  fi
}

wait_for_packages() {
  local profile="$1"
  local name
  local -a providers=(
    provider-minio
    provider-kubernetes
    provider-keycloak
    provider-helm
  )

  if [[ "${profile}" == complex ]]; then
    providers+=(
      provider-aws-s3
      provider-aws-iam
      upbound-provider-family-aws
      provider-ovh
    )
  fi

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
  local profile
  profile="$(selected_profile "${1:-}" "$0")"

  require_cluster
  require_provider_storage_tag

  kube apply -f "${MANIFEST_DIR}/namespaces.yaml"
  install_crossplane
  install_storage_dependencies "${profile}"
  install_datalab
  install_storage_configurations "${profile}"

  kube apply -f "${MANIFEST_DIR}/minio.yaml"
  kube rollout status deployment/default --namespace minio --timeout=5m
  wait_for_packages "${profile}"
  kube get providers.pkg.crossplane.io,functions.pkg.crossplane.io,configurations.pkg.crossplane.io
}

main "$@"
