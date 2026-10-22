#!/usr/bin/env bash
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

INTEGRATION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.bash
source "${INTEGRATION_DIR}/lib.bash"

: "${EDUCATES_DEPENDENCIES_VERSION:=2.2.1}"
: "${DATA_CLIENT_IMAGE:=curlimages/curl:8.10.1}"
: "${KEEP_DATA_RESOURCES:=0}"

readonly EDUCATES_NAMESPACE=educates
readonly ENABLED_DATALAB=verify-data-enabled
readonly ENABLED_STORAGE_SECRET=verify-data-enabled
readonly PACKAGE_R_NAME=package-r
readonly PACKAGE_R_ENDPOINT=http://default-hl.minio:9000
readonly PROBE_NAME=verify-data-health
readonly MINIO_ACCESS_KEY=minioadmin
readonly MINIO_ACCESS_KEY_B64=bWluaW9hZG1pbg==

enabled_runtime_namespace=""

# shellcheck source=educates.bash
source "${INTEGRATION_DIR}/educates.bash"

apply_data_datalabs() {
  log 'Applying the Data verification Datalab'
  apply_template "${MANIFEST_DIR}/data/storage-secrets.yaml" \
    ENABLED_STORAGE_SECRET "${ENABLED_STORAGE_SECRET}" \
    PACKAGE_R_ENDPOINT "${PACKAGE_R_ENDPOINT}" \
    WORKSPACE_NAMESPACE "${WORKSPACE_NAMESPACE}"
  apply_template "${MANIFEST_DIR}/data/datalabs.yaml" \
    ENABLED_DATALAB "${ENABLED_DATALAB}" \
    WORKSPACE_NAMESPACE "${WORKSPACE_NAMESPACE}" \
    ENABLED_STORAGE_SECRET "${ENABLED_STORAGE_SECRET}"
}

verify_package_access() {
  local namespace="$1" read_only="$2"

  log "Checking Data file access with read-only=${read_only}"
  kube delete "pod/${PROBE_NAME}" --namespace "${namespace}" \
    --ignore-not-found --wait=true
  if ! render_template "${MANIFEST_DIR}/data/client.yaml" \
    PROBE_NAME "${PROBE_NAME}" \
    PROBE_NAMESPACE "${namespace}" \
    CLIENT_IMAGE "${DATA_CLIENT_IMAGE}" \
    DATA_READ_ONLY "${read_only}" \
    DATALAB_SECRET "${ENABLED_DATALAB}-datalab" | kube apply -f -; then
    return 1
  fi

  wait_for_probe "${namespace}" "${PROBE_NAME}"
}

deployment_checksum() {
  local namespace="$1"

  kube get "deployment/${PACKAGE_R_NAME}" --namespace "${namespace}" -o json | \
    jq -r '.spec.template.metadata.annotations[
      "datalabs.pkg.internal/storage-secret-checksum"
    ] // ""'
}

package_pod_uid() {
  local namespace="$1"

  kube get pods --namespace "${namespace}" \
    --selector "app.kubernetes.io/name=${PACKAGE_R_NAME}" -o json | \
    jq -r '.items[0].metadata.uid // ""'
}

wait_for_runtime_access_key() {
  local namespace="$1" expected="$2"
  local deadline=$((SECONDS + 600))
  local actual=""

  while true; do
    actual="$(kube get "secret/${ENABLED_DATALAB}-datalab" \
      --namespace "${namespace}" \
      -o jsonpath='{.data.AWS_ACCESS_KEY_ID}' 2>/dev/null || true)"
    if [[ "${actual}" == "${expected}" ]]; then
      return
    fi
    if ((SECONDS >= deadline)); then
      printf 'The runtime storage Secret did not receive the credential update.\n' >&2
      return 1
    fi
    sleep 5
  done
}

wait_for_deployment_rotation() {
  local namespace="$1" previous_checksum="$2" previous_pod_uid="$3"
  local deadline=$((SECONDS + 600))
  local checksum="" pod_uid=""

  while true; do
    checksum="$(deployment_checksum "${namespace}" 2>/dev/null || true)"
    pod_uid="$(package_pod_uid "${namespace}" 2>/dev/null || true)"
    if [[ -n "${checksum}" && "${checksum}" != "${previous_checksum}" && \
      -n "${pod_uid}" && "${pod_uid}" != "${previous_pod_uid}" ]]; then
      kube rollout status "deployment/${PACKAGE_R_NAME}" \
        --namespace "${namespace}" --timeout=10m
      return
    fi
    if ((SECONDS >= deadline)); then
      printf 'The package-r Deployment did not rotate with its storage Secret.\n' >&2
      return 1
    fi
    sleep 5
  done
}

patch_source_access_key() {
  local value="$1"

  kube patch "secret/${ENABLED_STORAGE_SECRET}" \
    --namespace "${WORKSPACE_NAMESPACE}" --type=merge \
    --patch "{\"stringData\":{\"AWS_ACCESS_KEY_ID\":\"${value}\"}}" >/dev/null
}

verify_credential_rotation() {
  local namespace="$1"
  local initial_checksum initial_pod_uid
  initial_checksum="$(deployment_checksum "${namespace}")"
  initial_pod_uid="$(package_pod_uid "${namespace}")"
  [[ -n "${initial_checksum}" && -n "${initial_pod_uid}" ]] || return 1
  log 'Replacing initial test credentials and checking the workload restart'
  patch_source_access_key "${MINIO_ACCESS_KEY}" &&
    wait_for_runtime_access_key "${namespace}" "${MINIO_ACCESS_KEY_B64}" &&
    wait_for_deployment_rotation "${namespace}" "${initial_checksum}" "${initial_pod_uid}"
}

verify_read_only_access() {
  local namespace="$1"
  local previous_pod_uid pod_uid
  local deadline=$((SECONDS + 600))

  previous_pod_uid="$(package_pod_uid "${namespace}")"
  kube patch "datalab.pkg.internal/${ENABLED_DATALAB}" \
    --namespace "${WORKSPACE_NAMESPACE}" --type=merge \
    --patch '{"spec":{"data":{"readOnlyMount":true}}}' >/dev/null
  while true; do
    pod_uid="$(package_pod_uid "${namespace}" 2>/dev/null || true)"
    if [[ -n "${pod_uid}" && "${pod_uid}" != "${previous_pod_uid}" ]]; then
      break
    fi
    if ((SECONDS >= deadline)); then
      printf 'Data did not restart after the read-only setting changed.\n' >&2
      return 1
    fi
    sleep 5
  done
  kube rollout status "deployment/${PACKAGE_R_NAME}" \
    --namespace "${namespace}" --timeout=10m || return 1
  verify_package_access "${namespace}" true
}

show_data_diagnostics() {
  kube get \
    "datalab.pkg.internal/${ENABLED_DATALAB}" \
    --namespace "${WORKSPACE_NAMESPACE}" -o wide || true
  kube get objects.kubernetes.m.crossplane.io \
    --namespace "${WORKSPACE_NAMESPACE}" \
    --selector "crossplane.io/composite=${ENABLED_DATALAB}" || true
  if [[ -n "${enabled_runtime_namespace}" ]]; then
    kube get deployment,service,networkpolicy,pod,pvc \
      --namespace "${enabled_runtime_namespace}" || true
    kube get events --namespace "${enabled_runtime_namespace}" \
      --sort-by=.lastTimestamp || true
  fi
}

cleanup_successful_verification() {
  if [[ "${KEEP_DATA_RESOURCES}" == 1 ]]; then
    return
  fi

  if [[ -n "${enabled_runtime_namespace}" ]]; then
    kube delete "pod/${PROBE_NAME}" --namespace "${enabled_runtime_namespace}" \
      --ignore-not-found --wait=true
  fi
  kube delete \
    "datalab.pkg.internal/${ENABLED_DATALAB}" \
    --namespace "${WORKSPACE_NAMESPACE}" --ignore-not-found --wait=false
  if kube wait \
    "datalab.pkg.internal/${ENABLED_DATALAB}" \
    --namespace "${WORKSPACE_NAMESPACE}" --for=delete --timeout=10m; then
    kube delete secret \
      "${ENABLED_STORAGE_SECRET}" \
      --namespace "${WORKSPACE_NAMESPACE}" --ignore-not-found --wait=true
  else
    printf 'Data verification cleanup is still running; resources were kept for diagnosis.\n' >&2
  fi
}

main() {
  require_cluster
  require_command jq
  install_educates
  apply_data_datalabs

  if ! enabled_runtime_namespace="$(wait_for_runtime_namespace "${ENABLED_DATALAB}")" ||
    ! kube wait deployment/package-r --namespace "${enabled_runtime_namespace}" --for=create --timeout=5m ||
    ! kube rollout status deployment/package-r --namespace "${enabled_runtime_namespace}" --timeout=10m ||
    ! verify_credential_rotation "${enabled_runtime_namespace}" ||
    ! verify_package_access "${enabled_runtime_namespace}" false ||
    ! verify_read_only_access "${enabled_runtime_namespace}"; then
    show_data_diagnostics
    printf 'Data verification resources were kept for diagnosis.\n' >&2
    exit 1
  fi

  cleanup_successful_verification
}

main "$@"
