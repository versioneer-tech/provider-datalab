#!/usr/bin/env bash
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

INTEGRATION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.bash
source "${INTEGRATION_DIR}/lib.bash"

# shellcheck source=postgres.bash
source "${INTEGRATION_DIR}/postgres.bash"
source "${INTEGRATION_DIR}/snapshots.bash"
POSTGRES_SNAPSHOTS=false
: "${POSTGRES_CLIENT_IMAGE:=postgres:17}"
: "${KEEP_POSTGRES_RESOURCES:=0}"

readonly DATALAB_NAME=verify-postgres
readonly POSTGRES_NAMESPACE="${DATALAB_NAME}"
readonly POSTGRES_CLUSTER=pg0
readonly STORAGE_SECRET=verify-postgres
readonly CONNECTION_SECRET="${DATALAB_NAME}-postgres-pg0"
readonly POSTGRES_URL_KEY=verify_url
readonly PROBE_NAME=verify-postgres


apply_postgres_datalab() {
  log 'Applying the PostgreSQL verification Datalab'
  apply_template "${MANIFEST_DIR}/postgres/datalab.yaml" \
    DATALAB_NAME "${DATALAB_NAME}" \
    WORKSPACE_NAMESPACE "${WORKSPACE_NAMESPACE}" \
    STORAGE_SECRET "${STORAGE_SECRET}" \
    BACKUPS_ENABLED "${POSTGRES_SNAPSHOTS}"
}

wait_for_postgres() {
  local cluster
  for cluster in pg0 pg1; do
    kube wait "cluster.postgresql.cnpg.io/${cluster}" --namespace "${POSTGRES_NAMESPACE}" \
      --for=create --timeout=15m
    kube wait "cluster.postgresql.cnpg.io/${cluster}" --namespace "${POSTGRES_NAMESPACE}" \
      --for=condition=Ready --timeout=15m
    wait_for_connection_secret "${DATALAB_NAME}-postgres-${cluster}" "${DATALAB_NAME}" 900 \
      host port user password databases verify_url
  done
  kube wait databases.postgresql.cnpg.io --all --namespace "${POSTGRES_NAMESPACE}" \
    --for=jsonpath='{.status.applied}'=true --timeout=5m
  kube wait "datalabs.versioneer.at/${DATALAB_NAME}" --namespace "${WORKSPACE_NAMESPACE}" \
    --for=condition=Ready --timeout=5m
  kube get cluster.postgresql.cnpg.io/pg1 --namespace "${POSTGRES_NAMESPACE}" -o json \
    | jq -e '(.spec | has("backup") | not)' >/dev/null
  verify_workload_probes "${POSTGRES_NAMESPACE}"
  printf 'PASS PostgreSQL without backups is ready\n'
}

run_postgres_probe() {
  local secret_name="${1:-${CONNECTION_SECRET}}"
  local url_key="${2:-${POSTGRES_URL_KEY}}"

  kube wait networkpolicy/allow-internal-ingress --namespace "${POSTGRES_NAMESPACE}" \
    --for=create --timeout=5m
  log 'Running an in-cluster write/read probe through the Datalab Secret'
  resource_budget
  kube delete "pod/${PROBE_NAME}" --namespace "${WORKSPACE_NAMESPACE}" \
    --ignore-not-found --wait=true
  render_template "${MANIFEST_DIR}/postgres/client.yaml" \
    PROBE_NAME "${PROBE_NAME}" \
    PROBE_NAMESPACE "${WORKSPACE_NAMESPACE}" \
    CLIENT_IMAGE "${POSTGRES_CLIENT_IMAGE}" \
    CONNECTION_SECRET "${secret_name}" \
    POSTGRES_URL_KEY "${url_key}" | kube apply -f -

  wait_for_probe "${WORKSPACE_NAMESPACE}" "${PROBE_NAME}"
}

cleanup_successful_verification() {
  if [[ "${KEEP_POSTGRES_RESOURCES}" == 1 ]]; then
    return
  fi

  kube delete "pod/${PROBE_NAME}" --namespace "${WORKSPACE_NAMESPACE}" \
    --ignore-not-found --wait=true
  kube delete "datalabs.versioneer.at/${DATALAB_NAME}" \
    --namespace "${WORKSPACE_NAMESPACE}" --ignore-not-found --wait=false
  if kube wait "datalabs.versioneer.at/${DATALAB_NAME}" \
    --namespace "${WORKSPACE_NAMESPACE}" --for=delete --timeout=5m; then
    python3 "${INTEGRATION_DIR}/verify-service-connections.py" \
      --kubeconfig "${PROVIDER_DATALAB_KUBECONFIG}" --context "${KUBECTL_CONTEXT}" --namespace "${WORKSPACE_NAMESPACE}" --datalab "${DATALAB_NAME}" --deleted
    kube delete namespace "${POSTGRES_NAMESPACE}" \
      --ignore-not-found --wait=true --timeout=5m
    stop_unused_operator cnpg-system cnpg clusters.postgresql.cnpg.io
  else
    printf 'Datalab cleanup is still running; resources were kept for diagnosis.\n' >&2
    return 1
  fi
}

show_postgres_diagnostics() {
  kube get "datalabs.versioneer.at/${DATALAB_NAME}" \
    --namespace "${WORKSPACE_NAMESPACE}" -o wide || true
  kube get objects.kubernetes.m.crossplane.io \
    --namespace "${WORKSPACE_NAMESPACE}" \
    --selector "crossplane.io/composite=${DATALAB_NAME}" || true
  kube get clusters.postgresql.cnpg.io,pod,pvc,secret \
    --namespace "${POSTGRES_NAMESPACE}" || true
  kube get "secret/${CONNECTION_SECRET}" \
    --namespace "${WORKSPACE_NAMESPACE}" || true
  kube get events --namespace "${POSTGRES_NAMESPACE}" \
    --sort-by=.lastTimestamp || true
  kube get events --namespace "${WORKSPACE_NAMESPACE}" \
    --sort-by=.lastTimestamp || true
}

main() {
  require_cluster
  install_cnpg
  kube apply -f "${MANIFEST_DIR}/s3/keycloak.yaml"
  kube rollout status deployment/keycloak --namespace keycloak --timeout=10m
  if snapshot_tests_available "${POSTGRES_NAMESPACE}"; then POSTGRES_SNAPSHOTS=true; fi
  apply_postgres_datalab
  if ! wait_for_postgres; then
    show_postgres_diagnostics
    exit 1
  fi
  local type_check
  if type_check="$(kube patch datalabs.versioneer.at/verify-postgres --namespace workspace \
    --dry-run=server --type=merge --patch '{"spec":{"stores":{"pg1":{"type":"valkey"}}}}' 2>&1)"; then
    printf 'A store type change was accepted.\n' >&2
    exit 1
  fi
  grep -F 'Store type cannot change' <<<"${type_check}" >/dev/null
  printf 'PASS Kubernetes admission rejects a store type change\n'
  if ! run_postgres_probe || ! run_postgres_probe "${DATALAB_NAME}-postgres-pg1" verify_url; then
    show_postgres_diagnostics
    printf 'PostgreSQL verification resources were kept for diagnosis.\n' >&2
    exit 1
  fi
  local -a snapshot_options=()
  [[ "${POSTGRES_SNAPSHOTS}" == true ]] || snapshot_options+=(--skip-snapshots)
  python3 "${INTEGRATION_DIR}/verify-postgres.py" \
    --kubeconfig "${PROVIDER_DATALAB_KUBECONFIG}" --context "${KUBECTL_CONTEXT}" \
    "${snapshot_options[@]}"
  run_postgres_probe
  python3 "${INTEGRATION_DIR}/verify-service-connections.py" \
    --kubeconfig "${PROVIDER_DATALAB_KUBECONFIG}" --context "${KUBECTL_CONTEXT}" --namespace "${WORKSPACE_NAMESPACE}" --datalab "${DATALAB_NAME}"
  cleanup_successful_verification
}

main "$@"
