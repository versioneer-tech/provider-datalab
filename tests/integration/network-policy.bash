#!/usr/bin/env bash
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

probe_network_policy() (
  set -euo pipefail
  local namespace=test-network-capability server_ip result deadline
  local existing
  existing="$(kube get namespace "${namespace}" --ignore-not-found -o name)" || return 1
  if [[ -n "${existing}" ]]; then
    printf 'NetworkPolicy probe namespace %s already exists.\n' "${namespace}" >&2
    return 1
  fi
  kube create namespace "${namespace}" >/dev/null || return 1
  trap 'result=$?; kube delete namespace "${namespace}" --ignore-not-found --wait=true --timeout=60s >/dev/null || result=1; exit "${result}"' EXIT
  render_template "${MANIFEST_DIR}/network/server.yaml" \
    NAMESPACE "${namespace}" SERVER_IMAGE "${NETWORK_SERVER_IMAGE}" | kube apply -f - >/dev/null || return 1
  render_template "${MANIFEST_DIR}/network/client.yaml" \
    NAMESPACE "${namespace}" CLIENT_IMAGE "${NETWORK_CLIENT_IMAGE}" | kube apply -f - >/dev/null || return 1
  kube rollout status deployment/echo --namespace "${namespace}" --timeout=3m >/dev/null || return 1
  kube wait pod/client --namespace "${namespace}" --for=condition=Ready --timeout=3m >/dev/null || return 1
  server_ip="$(kube get pod --namespace "${namespace}" --selector app=echo -o jsonpath='{.items[0].status.podIP}')" || return 1
  [[ -n "${server_ip}" ]] || return 1
  probe_connection() {
    kube exec --namespace "${namespace}" client -- curl -fsS --connect-timeout 2 --max-time 3 \
      "http://${server_ip}:8080/" --output /dev/null >/dev/null 2>&1
  }
  probe_connection || {
    result=$?
    printf 'NetworkPolicy probe baseline connection failed (exit %s).\n' "${result}" >&2
    return 1
  }
  kube apply -f - >/dev/null <<POLICY || return 1
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: test-deny-ingress
  namespace: ${namespace}
spec:
  podSelector:
    matchLabels: {app: echo}
  policyTypes: [Ingress]
  ingress: []
POLICY
  deadline=$((SECONDS + 30))
  while true; do
    if probe_connection; then result=0; else result=$?; fi
    if [[ "${result}" == 7 || "${result}" == 28 ]]; then break; fi
    if [[ "${result}" != 0 ]] || ((SECONDS >= deadline)); then
      printf 'NetworkPolicy enforcement probe did not block traffic (exit %s).\n' "${result}" >&2
      return 1
    fi
    sleep 2
  done
  kube delete networkpolicy/test-deny-ingress --namespace "${namespace}" >/dev/null || return 1
  deadline=$((SECONDS + 30))
  until probe_connection; do
    ((SECONDS < deadline)) || { printf 'Traffic did not recover after policy removal.\n' >&2; return 1; }
    sleep 2
  done
)

network_policy_tests_available() {
  local reason
  if [[ "${PROVIDER_DATALAB_CLUSTER}" == existing && "${PROVIDER_DATALAB_SKIP_NETWORK_POLICY:-0}" == 1 ]]; then
    printf '\n=== SKIPPED: NetworkPolicy traffic tests: the selected virtual target does not enforce host NetworkPolicies. ===\n\n'
    return 1
  fi
  if reason="$(probe_network_policy 2>&1)"; then
    printf 'PASS NetworkPolicy enforcement probe: allowed, blocked, then allowed traffic.\n'
    return 0
  fi
  if [[ "${PROVIDER_DATALAB_CLUSTER}" == kind ]]; then
    printf 'ERROR: Kind NetworkPolicy setup is incomplete: %s\n' "${reason}" >&2
    exit 1
  fi
  printf '\n=== SKIPPED: NetworkPolicy traffic tests: %s ===\n\n' "${reason}"
  return 1
}
