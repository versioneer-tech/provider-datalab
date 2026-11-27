#!/usr/bin/env bash
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

set -Eeuo pipefail
INTEGRATION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${INTEGRATION_DIR}/lib.bash"
source "${INTEGRATION_DIR}/snapshots.bash"
: "${KEEP_VOLUME_RESOURCES:=0}"

diagnostics() {
  local result=$?
  trap - ERR
  kube get datalab/verify-volumes --namespace workspace || true
  kube get pvc,pods,cronjobs,jobs,volumesnapshots --namespace verify-volumes || true
  kube get events --namespace verify-volumes --sort-by=.lastTimestamp | tail -30 || true
  resource_budget || true
  printf 'Volume test resources were kept for diagnosis.\n' >&2
  exit "${result}"
}
trap diagnostics ERR

require_cluster
if ! snapshot_tests_available; then
  exit 0
fi
kube apply -f "${MANIFEST_DIR}/s3/keycloak.yaml"
kube rollout status deployment/keycloak --namespace keycloak --timeout=15m
apply_environment_config "${MANIFEST_DIR}/environment-configs/datalabs.yaml"
kube create secret generic verify-volumes --namespace workspace \
  --from-literal=AWS_ACCESS_KEY_ID=minioadmin --from-literal=AWS_SECRET_ACCESS_KEY=minioadmin \
  --from-literal=AWS_ENDPOINT_URL=http://default-hl.minio:9000 --from-literal=AWS_REGION=us-east-1 \
  --from-literal=AWS_S3_FORCE_PATH_STYLE=true --dry-run=client -o yaml | kube apply -f -
apply_environment_config "${MANIFEST_DIR}/volumes/environmentconfig.yaml"
kube apply -f "${MANIFEST_DIR}/volumes/datalab.yaml"
kube wait cronjob/volume-snapshot-analysis --namespace verify-volumes --for=create --timeout=10m
check_volume_backup_access verify-volumes volume-analysis volume-snapshot-analysis
python3 "${INTEGRATION_DIR}/verify-volumes.py" \
  --kubeconfig "${PROVIDER_DATALAB_KUBECONFIG}" --context "${KUBECTL_CONTEXT}" \
  --snapshot-class "${PROVIDER_DATALAB_SNAPSHOT_CLASS}"
if [[ "${KEEP_VOLUME_RESOURCES}" != 1 ]]; then
  kube delete datalab/verify-volumes --namespace workspace --wait=false
  kube wait datalab/verify-volumes --namespace workspace --for=delete --timeout=10m
  kube wait namespace/verify-volumes --for=delete --timeout=10m
  kube delete environmentconfig/datalab-volumes-it
  kube delete secret/verify-volumes --namespace workspace
fi
