#!/usr/bin/env bash
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

INTEGRATION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.bash
source "${INTEGRATION_DIR}/lib.bash"

if [[ "${PROVIDER_DATALAB_CLUSTER}" != kind || "${KUBECTL_CONTEXT}" != kind-provider-datalab-it ]]; then
  printf 'Cluster setup is only available for the dedicated Kind cluster.\n' >&2
  exit 2
fi
require_command docker
require_command kind
require_command kubectl

if ! docker info >/dev/null 2>&1; then
  printf 'Docker is not available. Start Docker before creating the cluster.\n' >&2
  exit 1
fi

docker ps --format '{{.Names}}' >/dev/null
nodes="$(docker ps -a --filter "label=io.x-k8s.kind.cluster=${KIND_CLUSTER_NAME}" --format '{{.Names}}')"
if [[ -n "${nodes}" ]]; then
  while IFS= read -r node; do
    state="$(docker inspect --format '{{.State.Status}}' "${node}")"
    case "${state}" in
      paused) docker unpause "${node}" >/dev/null ;;
      exited|created) docker start "${node}" >/dev/null ;;
      running) ;;
      *) printf 'Cannot reuse Kind node %s in state %s.\n' "${node}" "${state}" >&2; exit 2 ;;
    esac
  done <<<"${nodes}"
  kind_cluster_exists || { printf 'The matching Kind nodes did not form a usable cluster.\n' >&2; exit 2; }
  export_kind_kubeconfig
  printf 'Reusing kind cluster %s with context %s.\n' "${KIND_CLUSTER_NAME}" "${KUBECTL_CONTEXT}"
else
  if kind_cluster_exists; then
    printf 'Kind reports the cluster but its labelled Docker nodes are missing.\n' >&2
    exit 2
  fi
  log "Creating dedicated kind cluster ${KIND_CLUSTER_NAME}"
  KUBECONFIG="${PROVIDER_DATALAB_KUBECONFIG}" \
    kind create cluster \
      --name "${KIND_CLUSTER_NAME}" \
      --config "${MANIFEST_DIR}/kind.yaml" \
      --wait 5m
fi

deadline=$((SECONDS + 300))
until kube --request-timeout=5s get --raw=/readyz >/dev/null 2>&1; do
  ((SECONDS < deadline)) || { printf 'The Kind API did not become ready within five minutes.\n' >&2; exit 2; }
  sleep 2
done
kube wait nodes --all --for=condition=Ready --timeout=5m
log 'Preparing Kind NetworkPolicy enforcement'
kube apply -f https://raw.githubusercontent.com/kubernetes-sigs/kube-network-policies/v1.1.2/install.yaml
kube rollout status daemonset/kube-network-policies --namespace kube-system --timeout=5m
"${INTEGRATION_DIR}/kind-storage.bash"

