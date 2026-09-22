#!/usr/bin/env bash
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

INTEGRATION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${INTEGRATION_DIR}/../.." && pwd)"
MANIFEST_DIR="${INTEGRATION_DIR}/manifests"

readonly KIND_CLUSTER_NAME=provider-datalab-it
readonly KUBECTL_CONTEXT=kind-provider-datalab-it
readonly CROSSPLANE_NAMESPACE=crossplane
readonly WORKSPACE_NAMESPACE=workspace
: "${PROVIDER_DATALAB_KUBECONFIG:=/tmp/provider-datalab-it.kubeconfig}"
: "${PROVIDER_DATALAB_HELM_HOME:=/tmp/provider-datalab-it-helm}"
: "${CROSSPLANE_VERSION:=2.4.1}"
: "${KYVERNO_VERSION:=1.19.1}"
: "${KYVERNO_CHART_VERSION:=3.9.1}"

log() {
  printf '\n==> %s\n' "$*"
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf 'Missing required command: %s\n' "$1" >&2
    exit 1
  fi
}

kube() {
  command kubectl \
    --kubeconfig "${PROVIDER_DATALAB_KUBECONFIG}" \
    --context "${KUBECTL_CONTEXT}" \
    "$@"
}

helm_it() {
  mkdir -p \
    "${PROVIDER_DATALAB_HELM_HOME}/cache" \
    "${PROVIDER_DATALAB_HELM_HOME}/config" \
    "${PROVIDER_DATALAB_HELM_HOME}/data"
  HELM_CACHE_HOME="${PROVIDER_DATALAB_HELM_HOME}/cache" \
    HELM_CONFIG_HOME="${PROVIDER_DATALAB_HELM_HOME}/config" \
    HELM_DATA_HOME="${PROVIDER_DATALAB_HELM_HOME}/data" \
    command helm "$@"
}

kind_cluster_exists() {
  KUBECONFIG="${PROVIDER_DATALAB_KUBECONFIG}" \
    kind get clusters 2>/dev/null | grep -Fxq "${KIND_CLUSTER_NAME}"
}

export_kind_kubeconfig() {
  KUBECONFIG="${PROVIDER_DATALAB_KUBECONFIG}" \
    kind export kubeconfig --name "${KIND_CLUSTER_NAME}" >/dev/null
}

require_cluster() {
  require_command kind
  require_command kubectl

  if ! kind_cluster_exists; then
    printf 'The dedicated kind cluster %s is not available.\n' "${KIND_CLUSTER_NAME}" >&2
    printf 'Create it with tests/integration/create-cluster.bash.\n' >&2
    exit 2
  fi

  export_kind_kubeconfig
  if ! kube cluster-info >/dev/null 2>&1; then
    printf 'The context %s is not available in %s.\n' \
      "${KUBECTL_CONTEXT}" "${PROVIDER_DATALAB_KUBECONFIG}" >&2
    exit 2
  fi
}

render_template() {
  local source="$1"
  shift
  local rendered placeholder value

  rendered="$(<"${source}")"
  while (($#)); do
    if (($# < 2)); then
      printf 'Template variable has no value for %s.\n' "${source}" >&2
      exit 1
    fi
    placeholder="__$1__"
    value="$2"
    rendered="${rendered//${placeholder}/${value}}"
    shift 2
  done

  if grep -Eq '__[A-Z0-9_]+__' <<<"${rendered}"; then
    printf 'Unresolved placeholder in %s.\n' "${source}" >&2
    exit 1
  fi
  printf '%s\n' "${rendered}"
}

apply_template() {
  local source="$1"
  shift
  render_template "${source}" "$@" | kube apply -f -
}

wait_for_provider_runtime() {
  local name="$1"
  local revision

  kube wait "provider.pkg.crossplane.io/${name}" \
    --for=condition=Installed --timeout=15m
  revision="$(kube get "provider.pkg.crossplane.io/${name}" \
    -o jsonpath='{.status.currentRevision}')"
  if [[ -z "${revision}" ]]; then
    printf 'Provider %s has no active revision.\n' "${name}" >&2
    exit 1
  fi
  kube wait "providerrevision.pkg.crossplane.io/${revision}" \
    --for=condition=RevisionHealthy --timeout=20m
  kube wait "providerrevision.pkg.crossplane.io/${revision}" \
    --for=condition=RuntimeHealthy --timeout=20m
}

wait_for_crd_established() {
  local name="$1"
  local deadline=$((SECONDS + 120))

  until kube get "customresourcedefinition.apiextensions.k8s.io/${name}" \
    >/dev/null 2>&1; do
    if ((SECONDS >= deadline)); then
      printf 'CRD %s was not created within two minutes.\n' "${name}" >&2
      exit 1
    fi
    sleep 2
  done
  kube wait "customresourcedefinition.apiextensions.k8s.io/${name}" \
    --for=condition=Established --timeout=2m
}

selected_profile() {
  local value="${1:-}"
  case "${value}" in
    verify-network|verify-registry|verify-postgres)
      printf '%s\n' "${value}"
      ;;
    *)
      printf 'Usage: %s <verify-network|verify-registry|verify-postgres>\n' "$2" >&2
      exit 1
      ;;
  esac
}

install_kyverno() {
  require_command helm
  log "Installing Kyverno ${KYVERNO_VERSION} with chart ${KYVERNO_CHART_VERSION}"
  helm_it repo add kyverno https://kyverno.github.io/kyverno/ --force-update
  helm_it repo update kyverno
  helm_it upgrade --install kyverno kyverno/kyverno \
    --kubeconfig "${PROVIDER_DATALAB_KUBECONFIG}" \
    --kube-context "${KUBECTL_CONTEXT}" \
    --namespace kyverno \
    --create-namespace \
    --version "${KYVERNO_CHART_VERSION}" \
    --wait \
    --timeout 10m

  kube wait deployment \
    --namespace kyverno \
    --selector app.kubernetes.io/instance=kyverno \
    --for=condition=Available \
    --timeout=5m
}
