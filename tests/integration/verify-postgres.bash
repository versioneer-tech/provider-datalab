#!/usr/bin/env bash
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

INTEGRATION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.bash
source "${INTEGRATION_DIR}/lib.bash"

: "${PGO_VERSION:=6.0.1}"
: "${POSTGRES_CLIENT_IMAGE:=postgres:17}"
: "${KEEP_POSTGRES_RESOURCES:=0}"

readonly PGO_NAMESPACE=postgres-operator
readonly DATALAB_NAME=verify-postgres
readonly POSTGRES_NAMESPACE="${DATALAB_NAME}"
readonly POSTGRES_CLUSTER=pg0
readonly STORAGE_SECRET=verify-postgres
readonly DATALAB_SECRET="${DATALAB_NAME}-datalab"
readonly POSTGRES_URL_KEY=POSTGRES_PG0_VERIFY_URL
readonly PROBE_NAME=verify-postgres

install_pgo() {
  require_command helm
  log "Installing Crunchy PGO ${PGO_VERSION}"
  helm_it upgrade --install pgo \
    oci://registry.developers.crunchydata.com/crunchydata/pgo \
    --kubeconfig "${PROVIDER_DATALAB_KUBECONFIG}" \
    --kube-context "${KUBECTL_CONTEXT}" \
    --namespace "${PGO_NAMESPACE}" \
    --create-namespace \
    --version "${PGO_VERSION}" \
    --set singleNamespace=false \
    --wait \
    --timeout 10m
  kube rollout status deployment/pgo \
    --namespace "${PGO_NAMESPACE}" --timeout=5m
}

apply_postgres_datalab() {
  log 'Applying the PostgreSQL verification Datalab'
  if ! kube get customresourcedefinition.apiextensions.k8s.io/workshopenvironments.training.educates.dev \
    >/dev/null 2>&1; then
    kube create namespace "${POSTGRES_NAMESPACE}" \
      --dry-run=client -o yaml | kube apply -f -
  fi
  apply_template "${MANIFEST_DIR}/postgres/datalab.yaml" \
    DATALAB_NAME "${DATALAB_NAME}" \
    WORKSPACE_NAMESPACE "${WORKSPACE_NAMESPACE}" \
    STORAGE_SECRET "${STORAGE_SECRET}"
}

wait_for_postgres() {
  local deadline=$((SECONDS + 900))
  local owner ready_replicas repo_ready value

  log 'Waiting for the Datalab composition to create PostgreSQL'
  until kube get \
    "object.kubernetes.m.crossplane.io/db-postgrescluster-${DATALAB_NAME}-${POSTGRES_CLUSTER}" \
    --namespace "${WORKSPACE_NAMESPACE}" >/dev/null 2>&1 && \
    kube get \
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
    ready_replicas="$(kube get \
      "postgrescluster.postgres-operator.crunchydata.com/${POSTGRES_CLUSTER}" \
      --namespace "${POSTGRES_NAMESPACE}" \
      -o jsonpath='{.status.instances[?(@.name=="primary")].readyReplicas}' \
      2>/dev/null || true)"
    repo_ready="$(kube get \
      "postgrescluster.postgres-operator.crunchydata.com/${POSTGRES_CLUSTER}" \
      --namespace "${POSTGRES_NAMESPACE}" \
      -o jsonpath='{.status.pgbackrest.repoHost.ready}' \
      2>/dev/null || true)"
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

  log 'Waiting for the Datalab-generated PostgreSQL connection Secret'
  until value="$(kube get "secret/${DATALAB_SECRET}" \
    --namespace "${WORKSPACE_NAMESPACE}" \
    -o "jsonpath={.data.${POSTGRES_URL_KEY}}" 2>/dev/null)" && \
    [[ -n "${value}" ]]; do
    if ((SECONDS >= deadline)); then
      printf 'Datalab Secret %s/%s did not contain %s within 15 minutes.\n' \
        "${WORKSPACE_NAMESPACE}" "${DATALAB_SECRET}" \
        "${POSTGRES_URL_KEY}" >&2
      return 1
    fi
    sleep 5
  done

  owner="$(kube get "secret/${DATALAB_SECRET}" \
    --namespace "${WORKSPACE_NAMESPACE}" \
    -o 'jsonpath={.metadata.ownerReferences[?(@.kind=="Datalab")].name}')"
  if [[ "${owner}" != "${DATALAB_NAME}" ]]; then
    printf 'Secret %s/%s is not owned by Datalab %s.\n' \
      "${WORKSPACE_NAMESPACE}" "${DATALAB_SECRET}" "${DATALAB_NAME}" >&2
    return 1
  fi

  for key in \
    POSTGRES_PG0_HOST \
    POSTGRES_PG0_PORT \
    POSTGRES_PG0_USER \
    POSTGRES_PG0_PASSWORD \
    POSTGRES_PG0_DATABASES \
    "${POSTGRES_URL_KEY}"; do
    if [[ -z "$(kube get "secret/${DATALAB_SECRET}" \
      --namespace "${WORKSPACE_NAMESPACE}" \
      -o "jsonpath={.data.${key}}")" ]]; then
      printf 'Secret %s/%s does not contain key %s.\n' \
        "${WORKSPACE_NAMESPACE}" "${DATALAB_SECRET}" "${key}" >&2
      return 1
    fi
  done
}

run_postgres_probe() {
  local deadline=$((SECONDS + 300))
  local phase

  log 'Running an in-cluster write/read probe through the Datalab Secret'
  kube delete "pod/${PROBE_NAME}" --namespace "${WORKSPACE_NAMESPACE}" \
    --ignore-not-found --wait=true
  render_template "${MANIFEST_DIR}/postgres/client.yaml" \
    PROBE_NAME "${PROBE_NAME}" \
    PROBE_NAMESPACE "${WORKSPACE_NAMESPACE}" \
    CLIENT_IMAGE "${POSTGRES_CLIENT_IMAGE}" \
    DATALAB_SECRET "${DATALAB_SECRET}" \
    POSTGRES_URL_KEY "${POSTGRES_URL_KEY}" | kube apply -f -

  while true; do
    phase="$(kube get "pod/${PROBE_NAME}" --namespace "${WORKSPACE_NAMESPACE}" \
      -o jsonpath='{.status.phase}' 2>/dev/null || true)"
    case "${phase}" in
      Succeeded)
        kube logs "pod/${PROBE_NAME}" --namespace "${WORKSPACE_NAMESPACE}"
        return 0
        ;;
      Failed)
        kube logs "pod/${PROBE_NAME}" --namespace "${WORKSPACE_NAMESPACE}" || true
        kube describe "pod/${PROBE_NAME}" --namespace "${WORKSPACE_NAMESPACE}" || true
        return 1
        ;;
    esac
    if ((SECONDS >= deadline)); then
      printf 'PostgreSQL probe did not finish within five minutes.\n' >&2
      kube logs "pod/${PROBE_NAME}" --namespace "${WORKSPACE_NAMESPACE}" || true
      kube describe "pod/${PROBE_NAME}" --namespace "${WORKSPACE_NAMESPACE}" || true
      return 1
    fi
    sleep 5
  done
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
      --ignore-not-found --wait=true
  else
    printf 'Datalab cleanup is still running; resources were kept for diagnosis.\n' >&2
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
  kube get "secret/${DATALAB_SECRET}" \
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
  if ! run_postgres_probe; then
    show_postgres_diagnostics
    printf 'PostgreSQL verification resources were kept for diagnosis.\n' >&2
    exit 1
  fi
  cleanup_successful_verification
}

main "$@"
