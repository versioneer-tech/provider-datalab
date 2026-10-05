#!/usr/bin/env bash
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

INTEGRATION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.bash
source "${INTEGRATION_DIR}/lib.bash"

: "${MONGODB_OPERATOR_VERSION:=1.12.0}"
: "${REDIS_OPERATOR_CHART_VERSION:=0.26.1}"
: "${QDRANT_OPERATOR_VERSION:=0.0.3}"
: "${MONGO_CLIENT_IMAGE:=mongo:8.0.12}"
: "${REDIS_CLIENT_IMAGE:=redis:7.0.15}"
: "${QDRANT_CLIENT_IMAGE:=curlimages/curl:8.10.1}"
: "${KEEP_STORE_RESOURCES:=0}"

readonly STORE_NAME=verify
readonly store_type="${1:-}"

case "${store_type}" in
  mongo)
    DATALAB_NAME=verify-mongo
    OPERATOR_NAMESPACE=mongodb-operator
    OPERATOR_RELEASE=mongodb-kubernetes
    OPERATOR_DEPLOYMENT=mongodb-kubernetes-operator
    COMPOSED_OBJECT=mongodb-community-verify-mongo-verify
    RESOURCE_TYPE=mongodbcommunity.mongodbcommunity.mongodb.com
    RESOURCE_NAME=mongodb-verify
    POD_NAME=mongodb-verify-0
    SERVICE_NAME=mongodb-verify-svc
    CLIENT_IMAGE="${MONGO_CLIENT_IMAGE}"
    SECRET_KEYS=(
      MONGO_VERIFY_HOST MONGO_VERIFY_PORT MONGO_VERIFY_DATABASE
      MONGO_VERIFY_USER MONGO_VERIFY_PASSWORD MONGO_VERIFY_URI
    )
    ;;
  redis)
    DATALAB_NAME=verify-redis
    OPERATOR_NAMESPACE=redis-operator
    OPERATOR_RELEASE=redis-operator
    OPERATOR_DEPLOYMENT=redis-operator
    COMPOSED_OBJECT=redis-cache-verify-redis-verify
    RESOURCE_TYPE=redis.redis.redis.opstreelabs.in
    RESOURCE_NAME=verify
    POD_NAME=verify-0
    SERVICE_NAME=verify
    CLIENT_IMAGE="${REDIS_CLIENT_IMAGE}"
    SECRET_KEYS=(
      REDIS_VERIFY_HOST REDIS_VERIFY_PORT REDIS_VERIFY_USER
      REDIS_VERIFY_PASSWORD REDIS_VERIFY_DATABASE REDIS_VERIFY_URL
    )
    ;;
  qdrant)
    DATALAB_NAME=verify-qdrant
    OPERATOR_NAMESPACE=qdrant-operator
    OPERATOR_RELEASE=qdrant-operator
    OPERATOR_DEPLOYMENT=qdrant-operator
    COMPOSED_OBJECT=qdrant-vector-verify-qdrant-verify
    RESOURCE_TYPE=qdrantclusters.qdrant.io
    RESOURCE_NAME=verify
    POD_NAME=qdrant-verify-0
    SERVICE_NAME=qdrant-verify
    CLIENT_IMAGE="${QDRANT_CLIENT_IMAGE}"
    SECRET_KEYS=(
      QDRANT_VERIFY_HOST QDRANT_VERIFY_PORT QDRANT_VERIFY_GRPC_PORT
      QDRANT_VERIFY_URL QDRANT_VERIFY_API_KEY QDRANT_VERIFY_READ_API_KEY
    )
    ;;
  *)
    printf 'Usage: %s <mongo|redis|qdrant>\n' "$0" >&2
    exit 1
    ;;
esac

readonly DATALAB_NAME OPERATOR_NAMESPACE OPERATOR_RELEASE OPERATOR_DEPLOYMENT COMPOSED_OBJECT
readonly RESOURCE_TYPE RESOURCE_NAME POD_NAME SERVICE_NAME CLIENT_IMAGE
readonly STORAGE_SECRET="${DATALAB_NAME}"
readonly DATALAB_SECRET="${DATALAB_NAME}-datalab"
readonly PROBE_NAME="${DATALAB_NAME}"
readonly STORE_NAMESPACE="${DATALAB_NAME}"

install_mongo_operator() {
  log "Installing MongoDB Kubernetes Operator ${MONGODB_OPERATOR_VERSION}"
  helm_it repo add mongodb https://mongodb.github.io/helm-charts/ --force-update
  helm_it repo update mongodb
  helm_it upgrade --install "${OPERATOR_RELEASE}" mongodb/mongodb-kubernetes \
    --kubeconfig "${PROVIDER_DATALAB_KUBECONFIG}" \
    --kube-context "${KUBECTL_CONTEXT}" \
    --namespace "${OPERATOR_NAMESPACE}" \
    --create-namespace \
    --version "${MONGODB_OPERATOR_VERSION}" \
    --set-string 'operator.watchNamespace=*' \
    --set 'operator.watchedResources={mongodbcommunity}' \
    --wait \
    --timeout 10m
}

install_redis_operator() {
  log "Installing Redis Operator chart ${REDIS_OPERATOR_CHART_VERSION}"
  helm_it repo add opstree https://ot-container-kit.github.io/helm-charts/ \
    --force-update
  helm_it repo update opstree
  helm_it upgrade --install "${OPERATOR_RELEASE}" opstree/redis-operator \
    --kubeconfig "${PROVIDER_DATALAB_KUBECONFIG}" \
    --kube-context "${KUBECTL_CONTEXT}" \
    --namespace "${OPERATOR_NAMESPACE}" \
    --create-namespace \
    --version "${REDIS_OPERATOR_CHART_VERSION}" \
    --set issuer.create=false \
    --wait \
    --timeout 10m
}

install_qdrant_operator() {
  local archive chart_dir temp_dir
  local result=0

  require_command curl
  require_command tar
  temp_dir="$(mktemp -d /tmp/provider-datalab-qdrant.XXXXXX)"
  archive="${temp_dir}/qdrant-operator.tar.gz"
  curl --fail --silent --show-error --location \
    "https://github.com/qdrant-operator/qdrant-operator/archive/refs/tags/${QDRANT_OPERATOR_VERSION}.tar.gz" \
    --output "${archive}" || result=$?
  if ((result == 0)); then
    tar -xzf "${archive}" --directory "${temp_dir}" || result=$?
  fi
  if ((result == 0)); then
    chart_dir="$(find "${temp_dir}" -type d \
      -path '*/charts/qdrant-operator' -print -quit)"
    if [[ -z "${chart_dir}" ]]; then
      printf 'The Qdrant Operator archive does not contain its Helm chart.\n' >&2
      result=1
    fi
  fi
  if ((result == 0)); then
    log "Installing Qdrant Operator ${QDRANT_OPERATOR_VERSION}"
    helm_it upgrade --install "${OPERATOR_RELEASE}" "${chart_dir}" \
      --kubeconfig "${PROVIDER_DATALAB_KUBECONFIG}" \
      --kube-context "${KUBECTL_CONTEXT}" \
      --namespace "${OPERATOR_NAMESPACE}" \
      --create-namespace \
      --set image.repository=ghcr.io/qdrant-operator/qdrant-operator \
      --set-string "image.tag=${QDRANT_OPERATOR_VERSION}" \
      --set image.pullPolicy=IfNotPresent \
      --set metrics.enabled=false \
      --wait \
      --timeout 10m || result=$?
  fi
  rm -rf -- "${temp_dir}"
  return "${result}"
}

install_operator() {
  require_command helm
  case "${store_type}" in
    mongo) install_mongo_operator ;;
    redis) install_redis_operator ;;
    qdrant) install_qdrant_operator ;;
  esac
  kube wait "deployment/${OPERATOR_DEPLOYMENT}" \
    --namespace "${OPERATOR_NAMESPACE}" \
    --for=condition=Available --timeout=5m
  wait_for_crd_established "${RESOURCE_TYPE}"
}

apply_store_datalab() {
  log "Applying the ${store_type} verification Datalab"
  if ! kube get customresourcedefinition.apiextensions.k8s.io/workshopenvironments.training.educates.dev \
    >/dev/null 2>&1; then
    kube create namespace "${STORE_NAMESPACE}" \
      --dry-run=client -o yaml | kube apply -f -
  fi
  apply_template "${MANIFEST_DIR}/${store_type}/datalab.yaml" \
    DATALAB_NAME "${DATALAB_NAME}" \
    WORKSPACE_NAMESPACE "${WORKSPACE_NAMESPACE}" \
    STORAGE_SECRET "${STORAGE_SECRET}"
}

wait_for_store() {
  local deadline=$((SECONDS + 1200))
  local key owner value

  log "Waiting for the Datalab composition to create ${store_type}"
  until kube get "object.kubernetes.m.crossplane.io/${COMPOSED_OBJECT}" \
    --namespace "${WORKSPACE_NAMESPACE}" >/dev/null 2>&1 && \
    kube get "${RESOURCE_TYPE}/${RESOURCE_NAME}" \
      --namespace "${STORE_NAMESPACE}" >/dev/null 2>&1; do
    if ((SECONDS >= deadline)); then
      printf 'Datalab %s/%s did not create %s within 20 minutes.\n' \
        "${WORKSPACE_NAMESPACE}" "${DATALAB_NAME}" "${store_type}" >&2
      return 1
    fi
    sleep 5
  done

  if ! kube wait "pod/${POD_NAME}" --namespace "${STORE_NAMESPACE}" \
    --for=create --timeout=5m; then
    return 1
  fi
  if ! kube wait "pod/${POD_NAME}" --namespace "${STORE_NAMESPACE}" \
    --for=condition=Ready --timeout=20m; then
    return 1
  fi
  if ! kube wait "endpoints/${SERVICE_NAME}" --namespace "${STORE_NAMESPACE}" \
    --for=jsonpath='{.subsets[0].addresses[0].ip}' --timeout=5m; then
    return 1
  fi

  log 'Waiting for the Datalab-generated connection Secret'
  for key in "${SECRET_KEYS[@]}"; do
    until value="$(kube get "secret/${DATALAB_SECRET}" \
      --namespace "${WORKSPACE_NAMESPACE}" \
      -o "jsonpath={.data.${key}}" 2>/dev/null)" && [[ -n "${value}" ]]; do
      if ((SECONDS >= deadline)); then
        printf 'Datalab Secret %s/%s did not contain %s within 20 minutes.\n' \
          "${WORKSPACE_NAMESPACE}" "${DATALAB_SECRET}" "${key}" >&2
        return 1
      fi
      sleep 5
    done
  done

  owner="$(kube get "secret/${DATALAB_SECRET}" \
    --namespace "${WORKSPACE_NAMESPACE}" \
    -o 'jsonpath={.metadata.ownerReferences[?(@.kind=="Datalab")].name}')"
  if [[ "${owner}" != "${DATALAB_NAME}" ]]; then
    printf 'Secret %s/%s is not owned by Datalab %s.\n' \
      "${WORKSPACE_NAMESPACE}" "${DATALAB_SECRET}" "${DATALAB_NAME}" >&2
    return 1
  fi
}

run_store_probe() {
  local deadline=$((SECONDS + 300))
  local phase

  log "Running an in-cluster ${store_type} write/read probe"
  kube delete "pod/${PROBE_NAME}" --namespace "${WORKSPACE_NAMESPACE}" \
    --ignore-not-found --wait=true
  render_template "${MANIFEST_DIR}/${store_type}/client.yaml" \
    PROBE_NAME "${PROBE_NAME}" \
    PROBE_NAMESPACE "${WORKSPACE_NAMESPACE}" \
    CLIENT_IMAGE "${CLIENT_IMAGE}" \
    DATALAB_SECRET "${DATALAB_SECRET}" | kube apply -f -

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
      printf '%s probe did not finish within five minutes.\n' "${store_type}" >&2
      return 1
    fi
    sleep 5
  done
}

show_store_diagnostics() {
  kube get "datalab.pkg.internal/${DATALAB_NAME}" \
    --namespace "${WORKSPACE_NAMESPACE}" -o wide || true
  kube get objects.kubernetes.m.crossplane.io \
    --namespace "${WORKSPACE_NAMESPACE}" \
    --selector "crossplane.io/composite=${DATALAB_NAME}" || true
  kube get "${RESOURCE_TYPE}/${RESOURCE_NAME}" \
    --namespace "${STORE_NAMESPACE}" -o yaml || true
  kube get pod,pvc,service,secret --namespace "${STORE_NAMESPACE}" || true
  kube get "secret/${DATALAB_SECRET}" \
    --namespace "${WORKSPACE_NAMESPACE}" || true
  kube get events --namespace "${STORE_NAMESPACE}" \
    --sort-by=.lastTimestamp || true
}

cleanup_successful_verification() {
  if [[ "${KEEP_STORE_RESOURCES}" == 1 ]]; then
    return
  fi
  kube delete "pod/${PROBE_NAME}" --namespace "${WORKSPACE_NAMESPACE}" \
    --ignore-not-found --wait=true
  kube delete "datalab.pkg.internal/${DATALAB_NAME}" \
    --namespace "${WORKSPACE_NAMESPACE}" --ignore-not-found --wait=false
  if kube wait "datalab.pkg.internal/${DATALAB_NAME}" \
    --namespace "${WORKSPACE_NAMESPACE}" --for=delete --timeout=10m; then
    kube delete namespace "${STORE_NAMESPACE}" --ignore-not-found --wait=true
  else
    printf '%s cleanup is still running; resources were kept for diagnosis.\n' \
      "${store_type}" >&2
  fi
}

main() {
  require_cluster
  install_operator
  apply_store_datalab
  if ! wait_for_store; then
    show_store_diagnostics
    exit 1
  fi
  if ! run_store_probe; then
    show_store_diagnostics
    printf '%s verification resources were kept for diagnosis.\n' \
      "${store_type}" >&2
    exit 1
  fi
  cleanup_successful_verification
}

main
