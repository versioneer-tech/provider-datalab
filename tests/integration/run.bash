#!/usr/bin/env bash
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

profile=""
check_only=0
target_option=""
while (($#)); do
  case "$1" in
    --kind)
      [[ -z "${target_option}" ]] || { printf 'Select one cluster target.\n' >&2; exit 2; }
      target_option=kind
      export PROVIDER_DATALAB_CLUSTER=kind
      shift ;;
    --kubeconfig)
      [[ $# -ge 2 && -n "$2" && "$2" != --* && -z "${target_option}" ]] || { printf 'Supply one kubeconfig target.\n' >&2; exit 2; }
      target_option=existing
      export PROVIDER_DATALAB_CLUSTER=existing PROVIDER_DATALAB_KUBECONFIG="$2"
      shift 2 ;;
    --context|--storage-class|--snapshot-class|--service-cidr|--pod-cidrs|--image-registry|--docker-config|--image-pull-secret)
      [[ $# -ge 2 && -n "$2" && "$2" != --* ]] || { printf 'Missing value for %s.\n' "$1" >&2; exit 2; }
      case "$1" in
        --context) export PROVIDER_DATALAB_CONTEXT="$2" ;;
        --storage-class) export PROVIDER_DATALAB_STORAGE_CLASS="$2" ;;
        --snapshot-class) export PROVIDER_DATALAB_SNAPSHOT_CLASS="$2" ;;
        --service-cidr) export PROVIDER_DATALAB_SERVICE_CIDR="$2" ;;
        --pod-cidrs) export PROVIDER_DATALAB_POD_CIDRS="$2" ;;
        --image-registry) export PROVIDER_DATALAB_IMAGE_REGISTRY="$2" ;;
        --docker-config) export PROVIDER_DATALAB_DOCKER_CONFIG="$2" ;;
        --image-pull-secret) export PROVIDER_DATALAB_IMAGE_PULL_SECRET="$2" ;;
      esac
      shift 2 ;;
    --check) check_only=1; shift ;;
    --*) printf 'Unknown option: %s\n' "$1" >&2; exit 2 ;;
    *)
      [[ -z "${profile}" ]] || { printf 'Select one profile or all.\n' >&2; exit 2; }
      profile="$1"
      shift ;;
  esac
done

INTEGRATION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.bash
source "${INTEGRATION_DIR}/lib.bash"

if [[ "${profile}" == all ]]; then
  profiles=(verify-network verify-data verify-s3 verify-postgres verify-mongo verify-redis verify-registry verify-volumes verify-vcluster)
else
  profiles=("$(selected_profile "${profile}" "$0")")
fi
check_test_images "${profile}"
started=${SECONDS}
if [[ "${PROVIDER_DATALAB_CLUSTER}" == kind && "${check_only}" == 0 ]]; then
  "${INTEGRATION_DIR}/create-cluster.bash"
fi
check_cluster_settings
check_test_namespaces
if ((check_only)) && [[ "${profile}" == all || "${profile}" == verify-volumes || "${profile}" == verify-vcluster ]]; then
  source "${INTEGRATION_DIR}/snapshots.bash"
  snapshot_tests_available || true
  if [[ "${profile}" != verify-volumes ]]; then
    check_volume_binding_settings
  fi
fi
if ((check_only)); then
  exit 0
fi
"${INTEGRATION_DIR}/deploy-platform.bash"
if [[ "${profile}" == all ]]; then
  kube apply -f "${MANIFEST_DIR}/s3/keycloak.yaml"
fi
printf 'Platform setup passed in %s seconds.\n' "$((SECONDS - started))"

for profile in "${profiles[@]}"; do
  started=${SECONDS}
  resource_budget
  "${INTEGRATION_DIR}/${profile}.bash"
  resource_budget
  printf '\nIntegration profile %s completed in %s seconds (see PASS and SKIPPED results above).\n' "${profile}" "$((SECONDS - started))"
done
