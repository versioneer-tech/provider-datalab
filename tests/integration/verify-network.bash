#!/usr/bin/env bash
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

INTEGRATION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.bash
source "${INTEGRATION_DIR}/lib.bash"

: "${NETWORK_CLIENT_IMAGE:=curlimages/curl:8.10.1}"
: "${NETWORK_SERVER_IMAGE:=nginx:1.27-alpine}"
: "${NETWORK_VCLUSTER_IMAGE:=busybox:1.36.1}"
: "${NETWORK_EXTERNAL_URL:=https://example.com}"
: "${NETWORK_ITERATIONS:=3}"
: "${NETWORK_RESULTS_FILE:=/tmp/verify-network.tsv}"
: "${NETWORK_POLICY_SETTLE_SECONDS:=10}"
: "${KEEP_NETWORK_RESOURCES:=0}"

readonly DATALAB_OPEN=verify-network-open
readonly DATALAB_CLOSED=verify-network-closed
readonly NS_OPEN=verify-network-open
readonly NS_CLOSED=verify-network-closed
readonly NS_PEER=verify-network-peer
readonly NS_VCLUSTER=verify-network-vcluster
readonly POLICY_NAME=verify-network-guard
readonly OPEN_STORAGE_SECRET=verify-network-open
readonly CLOSED_STORAGE_SECRET=verify-network-closed

pass_count=0
fail_count=0

workshop_object_name() {
  printf 'workshop-%s\n' "$1"
}

generated_policy_exists() {
  local datalab="$1" policy="$2"
  kube get "object.kubernetes.m.crossplane.io/$(workshop_object_name "${datalab}")" \
    --namespace "${WORKSPACE_NAMESPACE}" -o json | \
    jq -e --arg policy "${policy}" '
      any(
        .spec.forProvider.manifest.spec.environment.objects[]?;
        .apiVersion == "networking.k8s.io/v1" and
        .kind == "NetworkPolicy" and
        .metadata.name == $policy
      )
    ' >/dev/null
}

require_generated_policy() {
  local datalab="$1" policy="$2"
  if ! generated_policy_exists "${datalab}" "${policy}"; then
    printf 'Datalab %s did not generate NetworkPolicy %s.\n' \
      "${datalab}" "${policy}" >&2
    exit 1
  fi
}

require_generated_policy_absent() {
  local datalab="$1" policy="$2"
  if generated_policy_exists "${datalab}" "${policy}"; then
    printf 'Datalab %s unexpectedly generated NetworkPolicy %s.\n' \
      "${datalab}" "${policy}" >&2
    exit 1
  fi
}

wait_for_generated_policies() {
  local datalab deadline count

  log 'Waiting for Datalab-generated NetworkPolicies'
  for datalab in "${DATALAB_OPEN}" "${DATALAB_CLOSED}"; do
    deadline=$((SECONDS + 300))
    while true; do
      count="$(kube get \
        "object.kubernetes.m.crossplane.io/$(workshop_object_name "${datalab}")" \
        --namespace "${WORKSPACE_NAMESPACE}" -o json 2>/dev/null | \
        jq '[
          .spec.forProvider.manifest.spec.environment.objects[]?
          | select(
              .apiVersion == "networking.k8s.io/v1" and
              .kind == "NetworkPolicy"
            )
        ] | length' 2>/dev/null || true)"
      if [[ "${count}" =~ ^[1-9][0-9]*$ ]]; then
        break
      fi
      if ((SECONDS >= deadline)); then
        printf 'Datalab %s did not generate NetworkPolicies within five minutes.\n' \
          "${datalab}" >&2
        exit 1
      fi
      sleep 5
    done
  done
}

verify_generated_policy_contract() {
  local policy

  log 'Checking Datalab-generated NetworkPolicy sets'
  for policy in \
    deny-egress \
    allow-namespace-egress \
    allow-dns-egress \
    allow-external-egress \
    allow-vcluster-egress \
    allow-internal-egress; do
    require_generated_policy "${DATALAB_OPEN}" "${policy}"
  done

  for policy in \
    deny-egress \
    allow-namespace-egress \
    allow-internal-egress; do
    require_generated_policy "${DATALAB_CLOSED}" "${policy}"
  done

  for policy in \
    allow-dns-egress \
    allow-external-egress \
    allow-vcluster-egress; do
    require_generated_policy_absent "${DATALAB_CLOSED}" "${policy}"
  done
}

apply_generated_policies() {
  local datalab="$1" namespace="$2"

  kube get "object.kubernetes.m.crossplane.io/$(workshop_object_name "${datalab}")" \
    --namespace "${WORKSPACE_NAMESPACE}" -o json | \
    jq --arg namespace "${namespace}" '{
      apiVersion: "v1",
      kind: "List",
      items: [
        .spec.forProvider.manifest.spec.environment.objects[]?
        | select(
            .apiVersion == "networking.k8s.io/v1" and
            .kind == "NetworkPolicy"
          )
        | .metadata.namespace = $namespace
      ]
    }' | kube apply -f -
}

apply_verification_resources() {
  log 'Applying network verification resources'
  for namespace in "${NS_OPEN}" "${NS_CLOSED}" "${NS_PEER}" "${NS_VCLUSTER}"; do
    kube create namespace "${namespace}" --dry-run=client -o yaml | kube apply -f -
  done

  apply_template "${MANIFEST_DIR}/network/datalabs.yaml" \
    OPEN_DATALAB "${DATALAB_OPEN}" \
    CLOSED_DATALAB "${DATALAB_CLOSED}" \
    WORKSPACE_NAMESPACE "${WORKSPACE_NAMESPACE}" \
    OPEN_STORAGE_SECRET "${OPEN_STORAGE_SECRET}" \
    CLOSED_STORAGE_SECRET "${CLOSED_STORAGE_SECRET}"
  wait_for_generated_policies
  verify_generated_policy_contract
  apply_generated_policies "${DATALAB_OPEN}" "${NS_OPEN}"
  apply_generated_policies "${DATALAB_CLOSED}" "${NS_CLOSED}"

  kube label namespace "${NS_VCLUSTER}" \
    "training.educates.dev/environment.name=${DATALAB_OPEN}" \
    'training.educates.dev/session.objects=true' \
    --overwrite

  for namespace in "${NS_OPEN}" "${NS_CLOSED}" "${NS_PEER}"; do
    render_template "${MANIFEST_DIR}/network/server.yaml" \
      NAMESPACE "${namespace}" \
      SERVER_IMAGE "${NETWORK_SERVER_IMAGE}" | kube apply -f -
  done

  render_template "${MANIFEST_DIR}/network/vcluster-server.yaml" \
    NAMESPACE "${NS_VCLUSTER}" \
    VCLUSTER_IMAGE "${NETWORK_VCLUSTER_IMAGE}" | kube apply -f -

  render_template "${MANIFEST_DIR}/network/kyverno-policy.yaml" \
    POLICY_NAME "${POLICY_NAME}" \
    OPEN_NAMESPACE "${NS_OPEN}" \
    CLOSED_NAMESPACE "${NS_CLOSED}" \
    PEER_NAMESPACE "${NS_PEER}" \
    VCLUSTER_NAMESPACE "${NS_VCLUSTER}" | kube apply -f -

  for namespace in "${NS_OPEN}" "${NS_CLOSED}"; do
    kube delete pod/client --namespace "${namespace}" \
      --ignore-not-found --wait=true
    render_template "${MANIFEST_DIR}/network/client.yaml" \
      NAMESPACE "${namespace}" \
      CLIENT_IMAGE "${NETWORK_CLIENT_IMAGE}" | kube apply -f -
  done
}

wait_for_verification_resources() {
  local namespace
  for namespace in "${NS_OPEN}" "${NS_CLOSED}" "${NS_PEER}"; do
    kube rollout status deployment/echo --namespace "${namespace}" --timeout=3m
  done
  kube rollout status deployment/vcluster \
    --namespace "${NS_VCLUSTER}" --timeout=3m
  for namespace in "${NS_OPEN}" "${NS_CLOSED}"; do
    kube wait pod/client --namespace "${namespace}" \
      --for=condition=Ready --timeout=3m
  done
  printf 'Waiting %s seconds for NetworkPolicy convergence.\n' \
    "${NETWORK_POLICY_SETTLE_SECONDS}"
  sleep "${NETWORK_POLICY_SETTLE_SECONDS}"
}

pod_ip() {
  kube get pod --namespace "$1" --selector app=echo \
    -o jsonpath='{.items[0].status.podIP}'
}

service_ip() {
  kube get service/echo --namespace "$1" -o jsonpath='{.spec.clusterIP}'
}

vcluster_pod_ip() {
  kube get pod --namespace "${NS_VCLUSTER}" \
    --selector app=vcluster,release=my-vcluster \
    -o jsonpath='{.items[0].status.podIP}'
}

vcluster_service_ip() {
  kube get service/my-vcluster --namespace "${NS_VCLUSTER}" \
    -o jsonpath='{.spec.clusterIP}'
}

record_result() {
  local category="$1" name="$2" iteration="$3" expectation="$4"
  local observed="$5" duration_ms="$6" exit_code="$7"

  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "${category}" "${name}" "${iteration}" "${expectation}" \
    "${observed}" "${duration_ms}" "${exit_code}" >>"${NETWORK_RESULTS_FILE}"
  printf '%-10s %-52s iteration=%-2s %s (%s ms)\n' \
    "${category}" "${name}" "${iteration}" "${observed}" "${duration_ms}"
  if [[ "${observed}" == PASS ]]; then
    pass_count=$((pass_count + 1))
  else
    fail_count=$((fail_count + 1))
  fi
}

verify_connection() {
  local name="$1" namespace="$2" expectation="$3" command="$4"
  local output exit_code observed started_ms finished_ms duration_ms iteration

  for ((iteration = 1; iteration <= NETWORK_ITERATIONS; iteration++)); do
    started_ms="$(date +%s%3N)"
    set +e
    output="$(kube exec --namespace "${namespace}" client -- \
      sh -c "${command}" 2>&1)"
    exit_code=$?
    set -e
    finished_ms="$(date +%s%3N)"
    duration_ms=$((finished_ms - started_ms))

    observed=FAIL
    if [[ "${expectation}" == allow && "${exit_code}" == 0 ]]; then
      observed=PASS
    elif [[ "${expectation}" == block && "${exit_code}" != 0 ]]; then
      observed=PASS
    fi
    record_result network "${name}" "${iteration}" "${expectation}" \
      "${observed}" "${duration_ms}" "${exit_code}"
    if [[ "${observed}" == FAIL ]]; then
      printf '  exit=%s output=%s\n' "${exit_code}" "${output:-<empty>}"
    fi
  done
}

verify_admission_denied() {
  local name="$1" manifest="$2"
  local output exit_code observed started_ms finished_ms duration_ms

  started_ms="$(date +%s%3N)"
  set +e
  output="$(printf '%s\n' "${manifest}" | kube apply -f - 2>&1)"
  exit_code=$?
  set -e
  finished_ms="$(date +%s%3N)"
  duration_ms=$((finished_ms - started_ms))

  observed=FAIL
  if [[ "${exit_code}" != 0 && \
    "${output}" == *'must not use host namespaces, hostPath volumes, or privileged containers'* ]]; then
    observed=PASS
    record_result admission "${name}" 1 block "${observed}" \
      "${duration_ms}" "${exit_code}"
  else
    record_result admission "${name}" 1 block "${observed}" \
      "${duration_ms}" "${exit_code}"
    printf '  unexpected admission result exit=%s output=%s\n' \
      "${exit_code}" "${output:-<empty>}"
    kube delete pod/should-be-denied --namespace "${NS_OPEN}" \
      --ignore-not-found
  fi
}

run_network_checks() {
  local open_pod open_service closed_pod closed_service peer_pod peer_service
  local minio_service vcluster_pod vcluster_service

  open_pod="$(pod_ip "${NS_OPEN}")"
  open_service="$(service_ip "${NS_OPEN}")"
  closed_pod="$(pod_ip "${NS_CLOSED}")"
  closed_service="$(service_ip "${NS_CLOSED}")"
  peer_pod="$(pod_ip "${NS_PEER}")"
  peer_service="$(service_ip "${NS_PEER}")"
  minio_service="$(kube get service/default-hl --namespace minio \
    -o jsonpath='{.spec.clusterIP}')"
  vcluster_pod="$(vcluster_pod_ip)"
  vcluster_service="$(vcluster_service_ip)"

  verify_connection 'open: same-namespace Pod IP' "${NS_OPEN}" allow \
    "curl -fsS --connect-timeout 2 --max-time 5 http://${open_pod}/ >/dev/null"
  verify_connection 'open: same-namespace Service IP' "${NS_OPEN}" allow \
    "curl -fsS --connect-timeout 2 --max-time 5 http://${open_service}/ >/dev/null"
  verify_connection 'open: cross-namespace Pod IP' "${NS_OPEN}" block \
    "curl -fsS --connect-timeout 2 --max-time 5 http://${peer_pod}/ >/dev/null"
  verify_connection 'open: cross-namespace Service IP' "${NS_OPEN}" block \
    "curl -fsS --connect-timeout 2 --max-time 5 http://${peer_service}/ >/dev/null"
  verify_connection 'open: vCluster Pod IP' "${NS_OPEN}" allow \
    "curl -fsS --connect-timeout 2 --max-time 5 http://${vcluster_pod}:8443/ >/dev/null"
  verify_connection 'open: vCluster Service IP' "${NS_OPEN}" allow \
    "curl -fsS --connect-timeout 2 --max-time 5 http://${vcluster_service}:443/ >/dev/null"
  verify_connection 'open: AWS metadata IPv4' "${NS_OPEN}" block \
    'curl -fsS --connect-timeout 2 --max-time 5 http://169.254.169.254/ >/dev/null'
  verify_connection 'open: Scaleway metadata IPv4' "${NS_OPEN}" block \
    'curl -fsS --connect-timeout 2 --max-time 5 http://169.254.42.42/ >/dev/null'
  verify_connection 'open: external URL' "${NS_OPEN}" allow \
    "curl -fsS --connect-timeout 5 --max-time 15 ${NETWORK_EXTERNAL_URL} >/dev/null"
  verify_connection 'open: configured MinIO backend' "${NS_OPEN}" allow \
    "curl -fsS --connect-timeout 2 --max-time 5 http://${minio_service}:9000/minio/health/ready >/dev/null"

  verify_connection 'closed: same-namespace Pod IP' "${NS_CLOSED}" allow \
    "curl -fsS --connect-timeout 2 --max-time 5 http://${closed_pod}/ >/dev/null"
  verify_connection 'closed: same-namespace Service IP' "${NS_CLOSED}" allow \
    "curl -fsS --connect-timeout 2 --max-time 5 http://${closed_service}/ >/dev/null"
  verify_connection 'closed: cross-namespace Pod IP' "${NS_CLOSED}" block \
    "curl -fsS --connect-timeout 2 --max-time 5 http://${peer_pod}/ >/dev/null"
  verify_connection 'closed: cross-namespace Service IP' "${NS_CLOSED}" block \
    "curl -fsS --connect-timeout 2 --max-time 5 http://${peer_service}/ >/dev/null"
  verify_connection 'closed: vCluster Service IP' "${NS_CLOSED}" block \
    "curl -fsS --connect-timeout 2 --max-time 5 http://${vcluster_service}:443/ >/dev/null"
  verify_connection 'closed: external URL' "${NS_CLOSED}" block \
    "curl -fsS --connect-timeout 5 --max-time 15 ${NETWORK_EXTERNAL_URL} >/dev/null"
  verify_connection 'closed: configured MinIO backend' "${NS_CLOSED}" allow \
    "curl -fsS --connect-timeout 2 --max-time 5 http://${minio_service}:9000/minio/health/ready >/dev/null"

  verify_connection 'normal Pod: no Docker socket' "${NS_OPEN}" allow \
    'test ! -S /var/run/docker.sock'
  verify_connection 'normal Pod: no host root mount' "${NS_OPEN}" allow \
    'test ! -e /host/etc/shadow'
}

run_admission_checks() {
  verify_admission_denied 'admission: deny privileged container' "$(cat <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: should-be-denied
  namespace: ${NS_OPEN}
spec:
  restartPolicy: Never
  containers:
  - name: denied
    image: busybox:1.36.1
    command: ["sh", "-c", "sleep 1"]
    securityContext:
      privileged: true
EOF
)"

  verify_admission_denied 'admission: deny hostNetwork' "$(cat <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: should-be-denied
  namespace: ${NS_OPEN}
spec:
  hostNetwork: true
  restartPolicy: Never
  containers:
  - name: denied
    image: busybox:1.36.1
    command: ["sh", "-c", "sleep 1"]
EOF
)"

  verify_admission_denied 'admission: deny Docker socket hostPath' "$(cat <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: should-be-denied
  namespace: ${NS_OPEN}
spec:
  restartPolicy: Never
  containers:
  - name: denied
    image: busybox:1.36.1
    command: ["sh", "-c", "sleep 1"]
    volumeMounts:
    - name: docker-sock
      mountPath: /var/run/docker.sock
  volumes:
  - name: docker-sock
    hostPath:
      path: /var/run/docker.sock
      type: Socket
EOF
)"
}

cleanup_successful_verification() {
  if [[ "${KEEP_NETWORK_RESOURCES}" == 1 ]]; then
    return
  fi
  kube delete validatingpolicy.policies.kyverno.io "${POLICY_NAME}" \
    --ignore-not-found
  kube delete datalabs.pkg.internal "${DATALAB_OPEN}" "${DATALAB_CLOSED}" \
    --namespace "${WORKSPACE_NAMESPACE}" --ignore-not-found --wait=false
  if kube wait datalabs.pkg.internal "${DATALAB_OPEN}" "${DATALAB_CLOSED}" \
    --namespace "${WORKSPACE_NAMESPACE}" --for=delete --timeout=5m; then
    kube delete namespace \
      "${NS_OPEN}" "${NS_CLOSED}" "${NS_PEER}" "${NS_VCLUSTER}" \
      --ignore-not-found --wait=true
  else
    printf 'Datalab cleanup is still running; resources were kept for diagnosis.\n' >&2
  fi
}

print_benchmark_summary() {
  printf '\nNetwork benchmark results: %s\n' "${NETWORK_RESULTS_FILE}"
  awk -F '\t' '
    NR == 1 { next }
    {
      key = $1 SUBSEP $2
      count[key]++
      total[key] += $6
      if ($5 != "PASS") failures[key]++
    }
    END {
      printf "%-10s %-52s %-10s %s\n", "category", "case", "average_ms", "failures"
      for (key in count) {
        split(key, part, SUBSEP)
        printf "%-10s %-52s %-10.1f %d\n", \
          part[1], part[2], total[key] / count[key], failures[key] + 0
      }
    }
  ' "${NETWORK_RESULTS_FILE}"
}

main() {
  require_cluster
  require_command jq
  install_kyverno
  apply_verification_resources
  wait_for_verification_resources
  printf 'category\tcase\titeration\texpectation\tobserved\tduration_ms\texit_code\n' \
    >"${NETWORK_RESULTS_FILE}"
  run_network_checks
  run_admission_checks
  print_benchmark_summary

  printf '\nNetwork verification totals: PASS=%s FAIL=%s\n' \
    "${pass_count}" "${fail_count}"
  if ((fail_count != 0)); then
    printf 'Verification resources were kept for diagnosis.\n' >&2
    exit 1
  fi
  cleanup_successful_verification
}

main "$@"
