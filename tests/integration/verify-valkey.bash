#!/usr/bin/env bash
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

INTEGRATION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.bash
source "${INTEGRATION_DIR}/lib.bash"
source "${INTEGRATION_DIR}/snapshots.bash"

: "${VALKEY_CLIENT_IMAGE:=valkey/valkey:9.2.0-alpine@sha256:c8e2d17498838af5d91e12eb7c11220b3434a7b7131a333e3af52ad5e0b80882}"
: "${KEEP_VALKEY_RESOURCES:=0}"

readonly store_type=valkey
readonly DATALAB_NAME=verify-valkey RESOURCE_TYPE=statefulset RESOURCE_NAME=valkey-verify
readonly POD_NAME=valkey-verify-0 SERVICE_NAME=valkey-verify CLIENT_IMAGE="${VALKEY_CLIENT_IMAGE}"
readonly SECRET_KEYS=(host port user password database url)
readonly STORAGE_SECRET="${DATALAB_NAME}"
readonly CONNECTION_SECRET="${DATALAB_NAME}-${store_type}-verify"
readonly PROBE_NAME="${DATALAB_NAME}"
readonly STORE_NAMESPACE="${DATALAB_NAME}"
probe_value=""

apply_store_datalab() {
  log "Applying the ${store_type} verification Datalab"
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

  verify_workload_probes "${STORE_NAMESPACE}" || return 1
  wait_for_connection_secret "${CONNECTION_SECRET}" "${DATALAB_NAME}" 1200 "${SECRET_KEYS[@]}"
}

valkey_prefix=""
valkey_other_prefix=""

run_store_probe() {
  local prefixes
  prefixes="$(kube get "secret/${CONNECTION_SECRET}" --namespace "${WORKSPACE_NAMESPACE}" \
    -o jsonpath='{.data.prefixes}' | python3 -c '
import base64, json, sys
value = json.loads(base64.b64decode(sys.stdin.read()))
assert value == {"sessions": "sessions:", "jobs": "jobs:"}
print(value["sessions"], value["jobs"])
')"
  read -r valkey_prefix valkey_other_prefix <<<"${prefixes}"
  kube wait networkpolicy/allow-internal-ingress --namespace "${STORE_NAMESPACE}" \
    --for=create --timeout=5m
  log "Running an in-cluster ${store_type} write/read probe"
  kube delete "pod/${PROBE_NAME}" --namespace "${WORKSPACE_NAMESPACE}" \
    --ignore-not-found --wait=true
  render_template "${MANIFEST_DIR}/${store_type}/client.yaml" \
    PROBE_NAME "${PROBE_NAME}" \
    PROBE_NAMESPACE "${WORKSPACE_NAMESPACE}" \
    CLIENT_IMAGE "${CLIENT_IMAGE}" \
    KEY_PREFIX "${valkey_prefix}" OTHER_KEY_PREFIX "${valkey_other_prefix}" \
    PROBE_VALUE "${probe_value}" \
    CONNECTION_SECRET "${CONNECTION_SECRET}" | kube apply -f -

  wait_for_probe "${WORKSPACE_NAMESPACE}" "${PROBE_NAME}"
}

set_valkey_backups() {
  local enabled="$1" previous_checksum checksum deadline=$((SECONDS + 600))
  local annotation='{.spec.template.metadata.annotations.datalabs\.versioneer\.at/valkey-acl-checksum}'
  previous_checksum="$(kube get "${RESOURCE_TYPE}/${RESOURCE_NAME}" \
    --namespace "${STORE_NAMESPACE}" -o "jsonpath=${annotation}")" || return 1
  kube patch "datalabs.versioneer.at/${DATALAB_NAME}" --namespace "${WORKSPACE_NAMESPACE}" \
    --type=merge --patch "{\"spec\":{\"stores\":{\"verify\":{\"backups\":${enabled}}}}}" || return 1
  while true; do
    checksum="$(kube get "${RESOURCE_TYPE}/${RESOURCE_NAME}" \
      --namespace "${STORE_NAMESPACE}" -o "jsonpath=${annotation}")" || return 1
    if [[ -n "${checksum}" && "${checksum}" != "${previous_checksum}" ]]; then break; fi
    if ((SECONDS >= deadline)); then
      printf 'Valkey did not update its ACL after backup settings changed.\n' >&2
      return 1
    fi
    sleep 5
  done
  kube rollout status "statefulset/${RESOURCE_NAME}" --namespace "${STORE_NAMESPACE}" --timeout=5m
}

verify_valkey_backup() {
  set_valkey_backups true || return 1
  kube wait cronjob/valkey-verify-backup --namespace "${STORE_NAMESPACE}" \
    --for=create --timeout=5m
  local claim
  claim="$(kube get pod/valkey-verify-0 --namespace "${STORE_NAMESPACE}" -o json | python3 -c '
import json, sys
pod = json.load(sys.stdin)
volumes = {v["name"]: v.get("persistentVolumeClaim", {}).get("claimName") for v in pod["spec"]["volumes"]}
claims = {volumes.get(m["name"]) for c in pod["spec"]["containers"] for m in c.get("volumeMounts", []) if m["mountPath"] == "/data"}
assert len(claims) == 1 and None not in claims
print(next(iter(claims)))
')"
  check_volume_backup_access "${STORE_NAMESPACE}" "${claim}" valkey-verify-backup || return 1
  python3 "${INTEGRATION_DIR}/verify-valkey.py" \
    --kubeconfig "${PROVIDER_DATALAB_KUBECONFIG}" --context "${KUBECTL_CONTEXT}" \
    --image "${CLIENT_IMAGE}" --value "${probe_value}" \
    --prefix "${valkey_prefix}" --other-prefix "${valkey_other_prefix}" || return 1
  run_store_probe
}

show_store_diagnostics() {
  kube get "datalabs.versioneer.at/${DATALAB_NAME}" \
    --namespace "${WORKSPACE_NAMESPACE}" -o wide || true
  kube get objects.kubernetes.m.crossplane.io \
    --namespace "${WORKSPACE_NAMESPACE}" \
    --selector "crossplane.io/composite=${DATALAB_NAME}" || true
  kube get "${RESOURCE_TYPE}/${RESOURCE_NAME}" \
    --namespace "${STORE_NAMESPACE}" -o yaml || true
  kube get pod,pvc,service,secret --namespace "${STORE_NAMESPACE}" || true
  kube get "secret/${CONNECTION_SECRET}" \
    --namespace "${WORKSPACE_NAMESPACE}" || true
  kube get events --namespace "${STORE_NAMESPACE}" \
    --sort-by=.lastTimestamp || true
}

cleanup_successful_verification() {
  if [[ "${KEEP_VALKEY_RESOURCES}" == 1 ]]; then
    return
  fi
  kube delete "pod/${PROBE_NAME}" --namespace "${WORKSPACE_NAMESPACE}" \
    --ignore-not-found --wait=true
  kube delete "datalabs.versioneer.at/${DATALAB_NAME}" \
    --namespace "${WORKSPACE_NAMESPACE}" --ignore-not-found --wait=false
  if kube wait "datalabs.versioneer.at/${DATALAB_NAME}" \
    --namespace "${WORKSPACE_NAMESPACE}" --for=delete --timeout=10m; then
    python3 "${INTEGRATION_DIR}/verify-service-connections.py" \
      --kubeconfig "${PROVIDER_DATALAB_KUBECONFIG}" --context "${KUBECTL_CONTEXT}" --namespace "${WORKSPACE_NAMESPACE}" --datalab "${DATALAB_NAME}" --deleted
    kube delete namespace "${STORE_NAMESPACE}" --ignore-not-found --wait=true --timeout=10m
  else
    printf '%s cleanup is still running; resources were kept for diagnosis.\n' \
      "${store_type}" >&2
    return 1
  fi
}

main() {
  require_cluster
  snapshot_tests_available verify-valkey || return 0
  require_command openssl
  probe_value="$(openssl rand -hex 12)"
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
  python3 "${INTEGRATION_DIR}/verify-service-connections.py" \
    --kubeconfig "${PROVIDER_DATALAB_KUBECONFIG}" --context "${KUBECTL_CONTEXT}" --namespace "${WORKSPACE_NAMESPACE}" --datalab "${DATALAB_NAME}"
  if ! verify_valkey_backup; then
    show_store_diagnostics
    printf 'Valkey backup verification resources were kept for diagnosis.\n' >&2
    exit 1
  fi
  cleanup_successful_verification
}

main
