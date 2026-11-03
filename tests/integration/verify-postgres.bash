#!/usr/bin/env bash
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

INTEGRATION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.bash
source "${INTEGRATION_DIR}/lib.bash"

# shellcheck source=postgres.bash
source "${INTEGRATION_DIR}/postgres.bash"
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
    STORAGE_SECRET "${STORAGE_SECRET}"
}

wait_for_postgres() {
  local deadline=$((SECONDS + 900))
  local ready_replicas repo_ready

  log 'Waiting for the Datalab composition to create PostgreSQL'
  until kube get \
      "postgrescluster.postgres-operator.crunchydata.com/${POSTGRES_CLUSTER}" \
      --namespace "${POSTGRES_NAMESPACE}" >/dev/null 2>&1; do
    if ((SECONDS >= deadline)); then
      printf 'Datalab %s/%s did not create PostgreSQL within 15 minutes.\n' \
        "${WORKSPACE_NAMESPACE}" "${DATALAB_NAME}" >&2
      return 1
    fi
    sleep 5
  done

  while true; do
    read -r ready_replicas repo_ready < <(kube get \
      "postgrescluster.postgres-operator.crunchydata.com/${POSTGRES_CLUSTER}" \
      --namespace "${POSTGRES_NAMESPACE}" -o json | \
      jq -r '[(.status.instances[]? | select(.name == "primary") | .readyReplicas), .status.pgbackrest.repoHost.ready] | @tsv')
    if [[ "${ready_replicas}" == 1 && "${repo_ready}" == true ]]; then
      break
    fi
    if ((SECONDS >= deadline)); then
      printf 'PostgresCluster %s/%s was not ready within 15 minutes.\n' \
        "${POSTGRES_NAMESPACE}" "${POSTGRES_CLUSTER}" >&2
      return 1
    fi
    sleep 5
  done

  log 'Checking PostgreSQL with zero backup storage'
  until kube get postgrescluster/pg1 --namespace "${POSTGRES_NAMESPACE}" -o json | \
    jq -e '(.spec | has("backups") | not) and any(.status.instances[]?; .name == "primary" and .readyReplicas >= 1)' >/dev/null; do
    if ((SECONDS >= deadline)); then
      printf 'PostgreSQL without backups did not become ready.\n' >&2
      return 1
    fi
    sleep 5
  done
  kube wait object.kubernetes.m.crossplane.io/db-postgrescluster-verify-postgres-pg1 \
    --namespace "${WORKSPACE_NAMESPACE}" --for=condition=Ready --timeout=5m

  wait_for_connection_secret "${CONNECTION_SECRET}" "${DATALAB_NAME}" 900 \
    host port user password databases "${POSTGRES_URL_KEY}"
  wait_for_connection_secret "${DATALAB_NAME}-postgres-pg1" "${DATALAB_NAME}" 900 verify_url

  log 'Waiting for the Datalab credentials to match the current operator Secret'
  until {
    kube get "secret/${POSTGRES_CLUSTER}-pguser-postgres" --namespace "${POSTGRES_NAMESPACE}" -o json
    kube get "secret/${CONNECTION_SECRET}" --namespace "${WORKSPACE_NAMESPACE}" -o json
  } | jq -se 'length == 2 and .[0].data.password == .[1].data.password' >/dev/null; do
    if ((SECONDS >= deadline)); then
      printf 'Datalab PostgreSQL credentials did not update from the operator Secret.\n' >&2
      return 1
    fi
    sleep 2
  done
}

run_postgres_probe() {
  local secret_name="${1:-${CONNECTION_SECRET}}"
  local url_key="${2:-${POSTGRES_URL_KEY}}"

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
  kube delete "datalab.pkg.internal/${DATALAB_NAME}" \
    --namespace "${WORKSPACE_NAMESPACE}" --ignore-not-found --wait=false
  if kube wait "datalab.pkg.internal/${DATALAB_NAME}" \
    --namespace "${WORKSPACE_NAMESPACE}" --for=delete --timeout=5m; then
    kube delete namespace "${POSTGRES_NAMESPACE}" \
      --ignore-not-found --wait=true --timeout=5m
    stop_unused_operator postgres-operator pgo postgresclusters.postgres-operator.crunchydata.com
  else
    printf 'Datalab cleanup is still running; resources were kept for diagnosis.\n' >&2
    return 1
  fi
}

show_postgres_diagnostics() {
  kube get "datalab.pkg.internal/${DATALAB_NAME}" \
    --namespace "${WORKSPACE_NAMESPACE}" -o wide || true
  kube get objects.kubernetes.m.crossplane.io \
    --namespace "${WORKSPACE_NAMESPACE}" \
    --selector "crossplane.io/composite=${DATALAB_NAME}" || true
  kube get postgrescluster,pod,pvc,secret \
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
  install_pgo
  apply_postgres_datalab
  if ! wait_for_postgres; then
    show_postgres_diagnostics
    exit 1
  fi
  if ! run_postgres_probe || ! run_postgres_probe "${DATALAB_NAME}-postgres-pg1" verify_url; then
    show_postgres_diagnostics
    printf 'PostgreSQL verification resources were kept for diagnosis.\n' >&2
    exit 1
  fi
  cleanup_successful_verification
}

main "$@"
