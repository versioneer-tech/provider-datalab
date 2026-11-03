#!/usr/bin/env bash
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

INTEGRATION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.bash
source "${INTEGRATION_DIR}/lib.bash"

: "${MONGODB_OPERATOR_VERSION:=1.14.0}"
: "${REDIS_OPERATOR_CHART_VERSION:=0.27.0}"
: "${MONGO_CLIENT_IMAGE:=mongo:8.0.12}"
: "${REDIS_CLIENT_IMAGE:=redis:7.0.15}"
: "${KEEP_STORE_RESOURCES:=0}"

readonly store_type="${1:-}"

case "${store_type}" in
  mongo)
    DATALAB_NAME=verify-mongo
    OPERATOR_NAMESPACE=mongodb-operator
    OPERATOR_RELEASE=mongodb-kubernetes
    OPERATOR_DEPLOYMENT=mongodb-kubernetes-operator
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
  *)
    printf 'Usage: %s <mongo|redis>\n' "$0" >&2
    exit 1
    ;;
esac

readonly DATALAB_NAME OPERATOR_NAMESPACE OPERATOR_RELEASE OPERATOR_DEPLOYMENT
readonly RESOURCE_TYPE RESOURCE_NAME POD_NAME SERVICE_NAME CLIENT_IMAGE
readonly STORAGE_SECRET="${DATALAB_NAME}"
readonly DATALAB_SECRET="${DATALAB_NAME}-datalab"
readonly PROBE_NAME="${DATALAB_NAME}"
readonly STORE_NAMESPACE="${DATALAB_NAME}"
probe_value=""

install_mongo_operator() {
  if helm_release_matches "${OPERATOR_RELEASE}" "${OPERATOR_NAMESPACE}" "mongodb-kubernetes-${MONGODB_OPERATOR_VERSION}"; then
    return
  fi
  log "Installing MongoDB Kubernetes Operator ${MONGODB_OPERATOR_VERSION}"
  helm_it repo add mongodb https://mongodb.github.io/helm-charts/ --force-update
  helm_it repo update mongodb
  apply_operator_crds mongodb/mongodb-kubernetes "${MONGODB_OPERATOR_VERSION}"
  helm_it upgrade --install "${OPERATOR_RELEASE}" mongodb/mongodb-kubernetes \
    --kubeconfig "${PROVIDER_DATALAB_KUBECONFIG}" \
    --kube-context "${KUBECTL_CONTEXT}" \
    --namespace "${OPERATOR_NAMESPACE}" \
    --create-namespace \
    --version "${MONGODB_OPERATOR_VERSION}" \
    --set-string 'operator.watchNamespace=*' \
    --set 'operator.watchedResources={mongodbcommunity}' \
    --set operator.resources.requests.cpu=100m \
    --set operator.resources.requests.memory=128Mi \
    --set operator.resources.limits.cpu=500m \
    --set operator.resources.limits.memory=512Mi \
    --wait \
    --timeout 10m
}

install_redis_operator() {
  if helm_release_matches "${OPERATOR_RELEASE}" "${OPERATOR_NAMESPACE}" "redis-operator-${REDIS_OPERATOR_CHART_VERSION}"; then
    return
  fi
  log "Installing Redis Operator chart ${REDIS_OPERATOR_CHART_VERSION}"
  helm_it repo add opstree https://ot-container-kit.github.io/helm-charts/ \
    --force-update
  helm_it repo update opstree
  apply_operator_crds opstree/redis-operator "${REDIS_OPERATOR_CHART_VERSION}"
  helm_it upgrade --install "${OPERATOR_RELEASE}" opstree/redis-operator \
    --kubeconfig "${PROVIDER_DATALAB_KUBECONFIG}" \
    --kube-context "${KUBECTL_CONTEXT}" \
    --namespace "${OPERATOR_NAMESPACE}" \
    --create-namespace \
    --version "${REDIS_OPERATOR_CHART_VERSION}" \
    --set issuer.create=false \
    --set resources.requests.cpu=100m \
    --set resources.requests.memory=128Mi \
    --set resources.limits.cpu=500m \
    --set resources.limits.memory=512Mi \
    --wait \
    --timeout 10m
}

install_operator() {
  require_command helm
  case "${store_type}" in
    mongo) install_mongo_operator ;;
    redis) install_redis_operator ;;
  esac
  kube set resources "deployment/${OPERATOR_DEPLOYMENT}" --namespace "${OPERATOR_NAMESPACE}" \
    --containers "${OPERATOR_DEPLOYMENT}" \
    --requests=cpu=100m,memory=128Mi --limits=cpu=500m,memory=512Mi
  start_operator "${OPERATOR_NAMESPACE}" "${OPERATOR_DEPLOYMENT}"
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

  log "Waiting for the Datalab composition to create ${store_type}"
  until kube get "${RESOURCE_TYPE}/${RESOURCE_NAME}" \
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

  wait_for_connection_secret "${DATALAB_SECRET}" "${DATALAB_NAME}" 1200 "${SECRET_KEYS[@]}"
}

run_store_probe() {

  log "Running an in-cluster ${store_type} write/read probe"
  kube delete "pod/${PROBE_NAME}" --namespace "${WORKSPACE_NAMESPACE}" \
    --ignore-not-found --wait=true
  render_template "${MANIFEST_DIR}/${store_type}/client.yaml" \
    PROBE_NAME "${PROBE_NAME}" \
    PROBE_NAMESPACE "${WORKSPACE_NAMESPACE}" \
    CLIENT_IMAGE "${CLIENT_IMAGE}" \
    PROBE_VALUE "${probe_value}" \
    DATALAB_SECRET "${DATALAB_SECRET}" | kube apply -f -

  wait_for_probe "${WORKSPACE_NAMESPACE}" "${PROBE_NAME}"
}

verify_mongo_backup() {
  local backup_job=verify-mongo-backup restore_probe=verify-mongo-restore
  log 'Running the MongoDB backup CronJob and restoring its archive'
  kube wait cronjob/mongodb-verify-backup --namespace "${STORE_NAMESPACE}" \
    --for=create --timeout=5m
  kube delete "job/${backup_job}" "pod/${restore_probe}" --namespace "${STORE_NAMESPACE}" \
    --ignore-not-found --wait=true
  kube create job "${backup_job}" --from=cronjob/mongodb-verify-backup \
    --namespace "${STORE_NAMESPACE}"
  wait_for_job_scheduling "${STORE_NAMESPACE}" "${backup_job}" || return 1
  if ! kube wait "job/${backup_job}" --namespace "${STORE_NAMESPACE}" \
    --for=condition=Complete --timeout=10m; then
    kube logs "job/${backup_job}" --namespace "${STORE_NAMESPACE}" --all-containers=true
    return 1
  fi
  render_template "${MANIFEST_DIR}/mongo/restore.yaml" \
    PROBE_NAME "${restore_probe}" STORE_NAMESPACE "${STORE_NAMESPACE}" \
    CLIENT_IMAGE "${CLIENT_IMAGE}" PROBE_VALUE "${probe_value}" | kube apply -f -
  wait_for_probe "${STORE_NAMESPACE}" "${restore_probe}"
}

set_redis_backup_storage() {
  local size="$1" previous_checksum checksum deadline=$((SECONDS + 600))
  local annotation='{.metadata.annotations.datalabs\.pkg\.internal/redis-acl-checksum}'
  previous_checksum="$(kube get "${RESOURCE_TYPE}/${RESOURCE_NAME}" \
    --namespace "${STORE_NAMESPACE}" -o "jsonpath=${annotation}")" || return 1
  kube patch "datalab.pkg.internal/${DATALAB_NAME}" --namespace "${WORKSPACE_NAMESPACE}" \
    --type=merge --patch "{\"spec\":{\"cacheStores\":{\"verify\":{\"backupStorage\":\"${size}\"}}}}" || return 1
  while true; do
    checksum="$(kube get "${RESOURCE_TYPE}/${RESOURCE_NAME}" \
      --namespace "${STORE_NAMESPACE}" -o "jsonpath=${annotation}")" || return 1
    if [[ -n "${checksum}" && "${checksum}" != "${previous_checksum}" ]]; then break; fi
    if ((SECONDS >= deadline)); then
      printf 'Redis did not update its ACL after backup storage changed.\n' >&2
      return 1
    fi
    sleep 5
  done
  kube wait "statefulset/${RESOURCE_NAME}" --namespace "${STORE_NAMESPACE}" \
    --for="jsonpath={.spec.template.metadata.annotations.datalabs\.pkg\.internal/redis-acl-checksum}=${checksum}" \
    --timeout=5m || return 1
  kube rollout status "statefulset/${RESOURCE_NAME}" --namespace "${STORE_NAMESPACE}" --timeout=5m
}

verify_redis_backup() {
  local backup_job=verify-redis-backup restore_probe=verify-redis-restore
  set_redis_backup_storage 1Gi || return 1
  log 'Running the Redis backup CronJob and restoring its snapshot'
  kube wait cronjob/redis-verify-backup --namespace "${STORE_NAMESPACE}" \
    --for=create --timeout=5m
  kube delete "job/${backup_job}" "pod/${restore_probe}" --namespace "${STORE_NAMESPACE}" \
    --ignore-not-found --wait=true
  kube create job "${backup_job}" --from=cronjob/redis-verify-backup \
    --namespace "${STORE_NAMESPACE}"
  wait_for_job_scheduling "${STORE_NAMESPACE}" "${backup_job}" || return 1
  if ! kube wait "job/${backup_job}" --namespace "${STORE_NAMESPACE}" \
    --for=condition=Complete --timeout=10m; then
    kube logs "job/${backup_job}" --namespace "${STORE_NAMESPACE}" --all-containers=true
    return 1
  fi
  render_template "${MANIFEST_DIR}/redis/restore.yaml" \
    PROBE_NAME "${restore_probe}" STORE_NAMESPACE "${STORE_NAMESPACE}" \
    PROBE_VALUE "${probe_value}" CLIENT_IMAGE "${CLIENT_IMAGE}" | kube apply -f -
  wait_for_probe "${STORE_NAMESPACE}" "${restore_probe}" || return 1
  log 'Disabling Redis backups while retaining the snapshot volume'
  set_redis_backup_storage 0Gi || return 1
  kube wait cronjob/redis-verify-backup --namespace "${STORE_NAMESPACE}" \
    --for=delete --timeout=5m || return 1
  kube get pvc/redis-verify-backup --namespace "${STORE_NAMESPACE}" || return 1
  run_store_probe
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
    kube delete namespace "${STORE_NAMESPACE}" --ignore-not-found --wait=true --timeout=10m
    stop_unused_operator "${OPERATOR_NAMESPACE}" "${OPERATOR_DEPLOYMENT}" "${RESOURCE_TYPE}"
  else
    printf '%s cleanup is still running; resources were kept for diagnosis.\n' \
      "${store_type}" >&2
    return 1
  fi
}

main() {
  require_cluster
  require_command openssl
  probe_value="$(openssl rand -hex 12)"
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
  if [[ "${store_type}" == mongo ]] && ! verify_mongo_backup; then
    show_store_diagnostics
    printf 'MongoDB backup verification resources were kept for diagnosis.\n' >&2
    exit 1
  fi
  if [[ "${store_type}" == redis ]] && ! verify_redis_backup; then
    show_store_diagnostics
    printf 'Redis backup verification resources were kept for diagnosis.\n' >&2
    exit 1
  fi
  cleanup_successful_verification
}

main
