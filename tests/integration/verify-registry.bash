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
readonly PROBE_NAME=verify-registry
registry_runtime_namespace=""
registry_connection_secret=""

# shellcheck source=educates.bash
source "${INTEGRATION_DIR}/educates.bash"

apply_registry_datalab() {
  log 'Applying the registry verification Datalab'
  kube apply -f "${MANIFEST_DIR}/environment-configs/datalabs.yaml"
  kube delete pod/verify-registry-bucket --namespace "${WORKSPACE_NAMESPACE}" \
    --ignore-not-found --wait=true
  apply_template "${MANIFEST_DIR}/registry/bucket.yaml" \
    WORKSPACE_NAMESPACE "${WORKSPACE_NAMESPACE}" CLIENT_IMAGE "${REGISTRY_CLIENT_IMAGE}"
  wait_for_probe "${WORKSPACE_NAMESPACE}" verify-registry-bucket
  kube delete pod/verify-registry-bucket --namespace "${WORKSPACE_NAMESPACE}" --wait=true
  kube apply -f "${MANIFEST_DIR}/registry/datalab.yaml"
}

wait_for_registry_session() {
  local deadline=$((SECONDS + 900))

  log 'Waiting for the Educates environment and session'
  if ! kube wait \
    "object.kubernetes.m.crossplane.io/workshopenvironment-${DATALAB_NAME}" \
    --namespace "${WORKSPACE_NAMESPACE}" \
    --for=create --timeout=5m; then
    return 1
  fi
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
              .metadata.labels["app.kubernetes.io/name"] == "registry"
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
  local service_data service_name service_ip service_port

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
  local deadline=$((SECONDS + 300))
  until [[ -n "${registry_connection_secret}" ]]; do
    registry_connection_secret="$(kube get "datalab.pkg.internal/${DATALAB_NAME}" \
      --namespace "${WORKSPACE_NAMESPACE}" -o json | jq -r '
        [.status.connections[]? | select(.type == "registry" and .name == "primary" and .ready)
          | .secretRef.name] | first // ""
      ')"
    if ((SECONDS >= deadline)); then
      printf 'The registry connection did not become ready within five minutes.\n' >&2
      return 1
    fi
    [[ -n "${registry_connection_secret}" ]] || sleep 5
  done
  wait_for_connection_secret "${registry_connection_secret}" "${DATALAB_NAME}" 300 user password || return 1

  log 'Running an authenticated registry blob write/read probe'
  kube delete "pod/${PROBE_NAME}" --namespace "${WORKSPACE_NAMESPACE}" \
    --ignore-not-found --wait=true
  if ! render_template "${MANIFEST_DIR}/registry/client.yaml" \
    PROBE_NAME "${PROBE_NAME}" \
    PROBE_NAMESPACE "${WORKSPACE_NAMESPACE}" \
    CLIENT_IMAGE "${REGISTRY_CLIENT_IMAGE}" \
    REGISTRY_URL "http://${service_ip}:${service_port}" \
    REGISTRY_SECRET "${registry_connection_secret}" | kube apply -f -; then
    return 1
  fi

  wait_for_probe "${WORKSPACE_NAMESPACE}" "${PROBE_NAME}"
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
  kube logs "pod/${PROBE_NAME}" --namespace "${WORKSPACE_NAMESPACE}" || true
  kube get events --namespace "${runtime_namespace}" \
    --sort-by=.lastTimestamp || true
}

cleanup_successful_verification() {
  if [[ "${KEEP_REGISTRY_RESOURCES}" == 1 ]]; then
    return
  fi
  kube delete "pod/${PROBE_NAME}" --namespace "${WORKSPACE_NAMESPACE}" \
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
  python3 "${INTEGRATION_DIR}/verify-session-storage.py" \
    --kubeconfig "${PROVIDER_DATALAB_KUBECONFIG}"
  cleanup_successful_verification
}

main "$@"
