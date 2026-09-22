#!/usr/bin/env bash
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

INTEGRATION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.bash
source "${INTEGRATION_DIR}/lib.bash"

: "${EDUCATES_DEPENDENCIES_VERSION:=2.2.1}"
: "${REGISTRY_CLIENT_IMAGE:=curlimages/curl:8.10.1}"
: "${KEEP_REGISTRY_RESOURCES:=0}"

readonly EDUCATES_NAMESPACE=educates
readonly DATALAB_NAME=verify-registry
readonly SESSION_NAME=default
readonly SESSION_SECRET="${DATALAB_NAME}-${SESSION_NAME}-session"
readonly PROBE_NAME=verify-registry
registry_runtime_namespace=""

create_ingress_certificate() {
  local certificate private_key
  local result=0

  require_command openssl
  certificate="$(mktemp /tmp/provider-datalab-registry-cert.XXXXXX)"
  private_key="$(mktemp /tmp/provider-datalab-registry-key.XXXXXX)"
  openssl req -x509 -newkey rsa:2048 -nodes -days 1 \
    -subj '/CN=*.lab.local' \
    -addext 'subjectAltName=DNS:*.lab.local' \
    -keyout "${private_key}" -out "${certificate}" >/dev/null 2>&1 || result=$?
  if ((result == 0)); then
    kube create secret tls wildcard-tls \
      --namespace "${WORKSPACE_NAMESPACE}" \
      --cert "${certificate}" --key "${private_key}" \
      --dry-run=client -o yaml | kube apply -f - || result=$?
  fi
  rm -f "${certificate}" "${private_key}"
  return "${result}"
}

install_educates() {
  require_command helm
  install_kyverno
  create_ingress_certificate

  log "Installing the EOEPCA+ Educates dependencies ${EDUCATES_DEPENDENCIES_VERSION}"
  helm_it upgrade --install educates \
    oci://ghcr.io/eoepca/workspace/workspace-dependencies-educates \
    --kubeconfig "${PROVIDER_DATALAB_KUBECONFIG}" \
    --kube-context "${KUBECTL_CONTEXT}" \
    --namespace "${EDUCATES_NAMESPACE}" \
    --create-namespace \
    --version "${EDUCATES_DEPENDENCIES_VERSION}" \
    --set clusterIngressDomain=lab.local \
    --set clusterIngressClass=nginx \
    --set tlsCertificateRef.name=wildcard-tls \
    --set tlsCertificateRef.namespace="${WORKSPACE_NAMESPACE}" \
    --wait \
    --timeout 15m

  kube rollout status deployment/secrets-manager \
    --namespace "${EDUCATES_NAMESPACE}" --timeout=5m
  kube rollout status deployment/session-manager \
    --namespace "${EDUCATES_NAMESPACE}" --timeout=5m
}

apply_registry_datalab() {
  log 'Applying the registry verification Datalab'
  kube apply -f "${MANIFEST_DIR}/registry/datalab.yaml"
}

wait_for_registry_session() {
  local deadline=$((SECONDS + 900))

  log 'Waiting for the Educates environment and registry session'
  if ! kube wait \
    "object.kubernetes.m.crossplane.io/workshopenvironment-${DATALAB_NAME}" \
    --namespace "${WORKSPACE_NAMESPACE}" \
    --for=condition=Ready --timeout=15m; then
    return 1
  fi
  if ! kube wait \
    "object.kubernetes.m.crossplane.io/workshopsession-${DATALAB_NAME}-${SESSION_NAME}" \
    --namespace "${WORKSPACE_NAMESPACE}" \
    --for=condition=Ready --timeout=15m; then
    return 1
  fi

  until [[ -n "${registry_runtime_namespace}" ]]; do
    registry_runtime_namespace="$(kube get \
      "object.kubernetes.m.crossplane.io/workshopenvironment-${DATALAB_NAME}" \
      --namespace "${WORKSPACE_NAMESPACE}" \
      -o jsonpath='{.status.atProvider.manifest.status.educates.namespace}' \
      2>/dev/null || true)"
    if ((SECONDS >= deadline)); then
      printf 'The registry Educates runtime namespace was not reported within 15 minutes.\n' >&2
      return 1
    fi
    [[ -n "${registry_runtime_namespace}" ]] || sleep 5
  done

  if ! kube wait "secret/${SESSION_SECRET}" \
    --namespace "${registry_runtime_namespace}" --for=create --timeout=5m; then
    return 1
  fi
}

find_registry_service() {
  local runtime_namespace="$1"
  local deadline=$((SECONDS + 300))
  local service=""

  while [[ -z "${service}" ]]; do
    service="$(kube get services --namespace "${runtime_namespace}" -o json | \
      jq -r '
        [
          .items[]
          | select(
              .metadata.labels["training.educates.dev/application"] == "registry" or
              (.metadata.name | contains("registry"))
            )
          | [
              .metadata.name,
              .spec.clusterIP,
              (.spec.ports[0].port | tostring)
            ]
          | @tsv
        ]
        | first // ""
      ')"
    if ((SECONDS >= deadline)); then
      printf 'No registry Service appeared in namespace %s within five minutes.\n' \
        "${runtime_namespace}" >&2
      return 1
    fi
    [[ -n "${service}" ]] || sleep 5
  done
  printf '%s\n' "${service}"
}

run_registry_probe() {
  local runtime_namespace="$1"
  local service_data service_name service_ip service_port phase
  local deadline=$((SECONDS + 300))

  if ! service_data="$(find_registry_service "${runtime_namespace}")"; then
    return 1
  fi
  IFS=$'\t' read -r service_name service_ip service_port <<<"${service_data}"
  if ! kube rollout status "deployment/${service_name}" \
    --namespace "${runtime_namespace}" --timeout=5m; then
    return 1
  fi
  if ! kube wait "endpoints/${service_name}" --namespace "${runtime_namespace}" \
    --for=jsonpath='{.subsets[0].addresses[0].ip}' --timeout=5m; then
    return 1
  fi

  log 'Running an authenticated registry blob write/read probe'
  kube delete "pod/${PROBE_NAME}" --namespace "${runtime_namespace}" \
    --ignore-not-found --wait=true
  if ! render_template "${MANIFEST_DIR}/registry/client.yaml" \
    PROBE_NAME "${PROBE_NAME}" \
    PROBE_NAMESPACE "${runtime_namespace}" \
    CLIENT_IMAGE "${REGISTRY_CLIENT_IMAGE}" \
    REGISTRY_URL "http://${service_ip}:${service_port}" \
    SESSION_SECRET "${SESSION_SECRET}" | kube apply -f -; then
    return 1
  fi

  while true; do
    phase="$(kube get "pod/${PROBE_NAME}" --namespace "${runtime_namespace}" \
      -o jsonpath='{.status.phase}' 2>/dev/null || true)"
    case "${phase}" in
      Succeeded)
        kube logs "pod/${PROBE_NAME}" --namespace "${runtime_namespace}"
        return 0
        ;;
      Failed)
        kube logs "pod/${PROBE_NAME}" --namespace "${runtime_namespace}" || true
        kube describe "pod/${PROBE_NAME}" --namespace "${runtime_namespace}" || true
        return 1
        ;;
    esac
    if ((SECONDS >= deadline)); then
      printf 'Registry probe did not finish within five minutes.\n' >&2
      return 1
    fi
    sleep 5
  done
}

show_registry_diagnostics() {
  local runtime_namespace="${1:-verify-registry}"

  kube get "datalab.pkg.internal/${DATALAB_NAME}" \
    --namespace "${WORKSPACE_NAMESPACE}" -o wide || true
  kube get objects.kubernetes.m.crossplane.io \
    --namespace "${WORKSPACE_NAMESPACE}" \
    --selector "crossplane.io/composite=${DATALAB_NAME}" || true
  kube get workshop,workshopenvironment,workshopsession --all-namespaces || true
  kube get pod,pvc,service,secret --namespace "${runtime_namespace}" || true
  kube get events --namespace "${runtime_namespace}" \
    --sort-by=.lastTimestamp || true
}

cleanup_successful_verification() {
  local runtime_namespace="$1"

  if [[ "${KEEP_REGISTRY_RESOURCES}" == 1 ]]; then
    return
  fi
  kube delete "pod/${PROBE_NAME}" --namespace "${runtime_namespace}" \
    --ignore-not-found --wait=true
  kube delete "datalab.pkg.internal/${DATALAB_NAME}" \
    --namespace "${WORKSPACE_NAMESPACE}" --ignore-not-found --wait=false
  if ! kube wait "datalab.pkg.internal/${DATALAB_NAME}" \
    --namespace "${WORKSPACE_NAMESPACE}" --for=delete --timeout=10m; then
    printf 'Registry cleanup is still running; resources were kept for diagnosis.\n' >&2
  fi
}

main() {
  require_cluster
  require_command jq
  install_educates
  apply_registry_datalab
  if ! wait_for_registry_session; then
    show_registry_diagnostics
    exit 1
  fi
  if ! run_registry_probe "${registry_runtime_namespace}"; then
    show_registry_diagnostics "${registry_runtime_namespace}"
    printf 'Registry verification resources were kept for diagnosis.\n' >&2
    exit 1
  fi
  cleanup_successful_verification "${registry_runtime_namespace}"
}

main "$@"
