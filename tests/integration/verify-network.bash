#!/usr/bin/env bash
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

INTEGRATION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.bash
source "${INTEGRATION_DIR}/lib.bash"

: "${NETWORK_CLIENT_IMAGE:=curlimages/curl:8.10.1}"
: "${NETWORK_SERVER_IMAGE:=nginx:1.27-alpine}"
: "${NETWORK_EXTERNAL_URL:=https://www.iana.org/}"
: "${NETWORK_POLICY_SETTLE_SECONDS:=10}"
: "${KEEP_NETWORK_RESOURCES:=0}"

readonly DATALAB_OPEN=verify-network-open
readonly DATALAB_CLOSED=verify-network-closed
readonly NS_OPEN=verify-network-open
readonly NS_CLOSED=verify-network-closed
readonly NS_PEER=verify-network-peer
readonly OPEN_STORAGE_SECRET=verify-network-open
readonly CLOSED_STORAGE_SECRET=verify-network-closed

pass_count=0
fail_count=0

wait_for_generated_policies() {
  local datalab
  for datalab in "${DATALAB_OPEN}" "${DATALAB_CLOSED}"; do
    kube wait "namespace/${datalab}" --for=create --timeout=5m
    kube wait "networkpolicy/deny-egress" --namespace "${datalab}" --for=create --timeout=5m
    kube wait "networkpolicy/allow-internal-egress" --namespace "${datalab}" --for=create --timeout=5m
  done
}

apply_verification_resources() {
  log 'Applying network verification resources'
  kube apply -f "${MANIFEST_DIR}/environment-configs/datalabs.yaml"
  kube patch environmentconfig datalab --type=merge --patch '{"data":{"defaults":{"security":{"externalEgress":false}}}}'
  kube patch environmentconfig datalab-custom --type=merge --patch '{"data":{"defaults":{"security":{"externalEgress":true}}}}'
  kube create namespace "${NS_PEER}" --dry-run=client -o yaml | kube apply -f -

  apply_template "${MANIFEST_DIR}/network/datalabs.yaml" \
    OPEN_DATALAB "${DATALAB_OPEN}" \
    CLOSED_DATALAB "${DATALAB_CLOSED}" \
    WORKSPACE_NAMESPACE "${WORKSPACE_NAMESPACE}" \
    OPEN_STORAGE_SECRET "${OPEN_STORAGE_SECRET}" \
    CLOSED_STORAGE_SECRET "${CLOSED_STORAGE_SECRET}"
  wait_for_generated_policies

  for namespace in "${NS_OPEN}" "${NS_CLOSED}" "${NS_PEER}"; do
    render_template "${MANIFEST_DIR}/network/server.yaml" \
      NAMESPACE "${namespace}" \
      SERVER_IMAGE "${NETWORK_SERVER_IMAGE}" | kube apply -f -
  done
}

wait_for_verification_resources() {
  local namespace
  for namespace in "${NS_OPEN}" "${NS_CLOSED}" "${NS_PEER}"; do
    kube rollout status deployment/echo --namespace "${namespace}" --timeout=3m
  done
  for namespace in "${NS_OPEN}" "${NS_CLOSED}"; do
    kube delete pod/client --namespace "${namespace}" \
      --ignore-not-found --wait=true
    render_template "${MANIFEST_DIR}/network/client.yaml" \
      NAMESPACE "${namespace}" \
      CLIENT_IMAGE "${NETWORK_CLIENT_IMAGE}" | kube apply -f -
  done

  for namespace in "${NS_OPEN}" "${NS_CLOSED}"; do
    kube wait pod/client --namespace "${namespace}" \
      --for=condition=Ready --timeout=3m
  done
  printf 'Waiting %s seconds for NetworkPolicy convergence.\n' \
    "${NETWORK_POLICY_SETTLE_SECONDS}"
  sleep "${NETWORK_POLICY_SETTLE_SECONDS}"
}

service_ip() {
  kube get service/echo --namespace "$1" -o jsonpath='{.spec.clusterIP}'
}

verify_connection() {
  local name="$1" namespace="$2" expectation="$3" command="$4"
  local output exit_code

  if output="$(kube exec --namespace "${namespace}" client -- sh -c "${command}" 2>&1)"; then
    exit_code=0
  else
    exit_code=$?
  fi

  # HTTP and command errors do not prove that a network policy blocked traffic.
  if [[ ("${expectation}" == allow && "${exit_code}" == 0) || \
    ("${expectation}" == block && ("${exit_code}" == 7 || "${exit_code}" == 28)) ]]; then
    pass_count=$((pass_count + 1))
    printf 'PASS %s\n' "${name}"
  else
    fail_count=$((fail_count + 1))
    printf 'FAIL %s: exit=%s output=%s\n' "${name}" "${exit_code}" "${output:-<empty>}"
  fi
}

run_network_checks() {
  local open_service closed_service peer_service
  local minio_service
  local external_ip external_target

  open_service="$(service_ip "${NS_OPEN}")"
  closed_service="$(service_ip "${NS_CLOSED}")"
  peer_service="$(service_ip "${NS_PEER}")"
  minio_service="$(kube get service/default-hl --namespace minio \
    -o jsonpath='{.spec.clusterIP}')"

  # The closed environment can block DNS as well as external traffic.
  external_ip="$(kube exec --namespace "${NS_OPEN}" client -- curl -4 -fsS \
    --connect-timeout 5 --max-time 15 --output /dev/null --write-out '%{remote_ip}' "${NETWORK_EXTERNAL_URL}")"
  external_target="$(python3 -c 'import sys; from urllib.parse import urlsplit; u = urlsplit(sys.argv[1]); print("{}:{}".format(u.hostname, u.port or {"http": 80, "https": 443}[u.scheme]))' "${NETWORK_EXTERNAL_URL}")"
  [[ -n "${external_ip}" ]]

  verify_connection 'open: same-namespace Service IP' "${NS_OPEN}" allow \
    "curl -fsS --connect-timeout 2 --max-time 5 http://${open_service}/ >/dev/null"
  verify_connection 'open: cross-namespace Service IP' "${NS_OPEN}" block \
    "curl -fsS --connect-timeout 2 --max-time 5 http://${peer_service}/ >/dev/null"
  verify_connection 'open: external URL' "${NS_OPEN}" allow \
    "curl -fsS --connect-timeout 5 --max-time 15 ${NETWORK_EXTERNAL_URL} >/dev/null"
  verify_connection 'open: configured MinIO backend' "${NS_OPEN}" allow \
    "curl -fsS --connect-timeout 2 --max-time 5 http://${minio_service}:9000/minio/health/ready >/dev/null"

  verify_connection 'closed: same-namespace Service IP' "${NS_CLOSED}" allow \
    "curl -fsS --connect-timeout 2 --max-time 5 http://${closed_service}/ >/dev/null"
  verify_connection 'closed: cross-namespace Service IP' "${NS_CLOSED}" block \
    "curl -fsS --connect-timeout 2 --max-time 5 http://${peer_service}/ >/dev/null"
  verify_connection 'closed: external URL' "${NS_CLOSED}" block \
    "curl -4 -fsS --resolve ${external_target}:${external_ip} --connect-timeout 5 --max-time 15 ${NETWORK_EXTERNAL_URL} >/dev/null"
  verify_connection 'closed: configured MinIO backend' "${NS_CLOSED}" allow \
    "curl -fsS --connect-timeout 2 --max-time 5 http://${minio_service}:9000/minio/health/ready >/dev/null"
}

cleanup_successful_verification() {
  if [[ "${KEEP_NETWORK_RESOURCES}" == 1 ]]; then
    return
  fi
  kube delete datalabs.pkg.internal "${DATALAB_OPEN}" "${DATALAB_CLOSED}" --namespace "${WORKSPACE_NAMESPACE}" --ignore-not-found --wait=false
  kube wait datalabs.pkg.internal "${DATALAB_OPEN}" "${DATALAB_CLOSED}" --namespace "${WORKSPACE_NAMESPACE}" --for=delete --timeout=10m
  kube delete "namespace/${NS_PEER}" --ignore-not-found --wait=true
}

main() {
  require_cluster
  require_command jq
  require_command python3
  apply_verification_resources
  wait_for_verification_resources
  run_network_checks

  printf '\nNetwork verification totals: PASS=%s FAIL=%s\n' \
    "${pass_count}" "${fail_count}"
  if ((fail_count != 0)); then
    printf 'Verification resources were kept for diagnosis.\n' >&2
    exit 1
  fi
  cleanup_successful_verification
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
