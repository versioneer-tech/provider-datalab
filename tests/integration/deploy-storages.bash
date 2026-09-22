#!/usr/bin/env bash
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

INTEGRATION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.bash
source "${INTEGRATION_DIR}/lib.bash"

backend="$(selected_backend "${1:-}" "$0")"

deploy_minio() {
  apply_template \
    "${MANIFEST_DIR}/provider-configs/minio.yaml" \
    WORKSPACE_NAMESPACE "${WORKSPACE_NAMESPACE}"
  kube apply -f "${MANIFEST_DIR}/environment-configs/storage-minio.yaml"
  kube apply -f "${MANIFEST_DIR}/storages/minio.yaml"
}

deploy_aws() {
  local bucket_name
  : "${CROSSPLANE_AWS_ACCOUNT_ID:?Set CROSSPLANE_AWS_ACCOUNT_ID to the 12-digit AWS account ID.}"
  : "${CROSSPLANE_AWS_REGION:=eu-central-1}"
  if [[ ! "${CROSSPLANE_AWS_ACCOUNT_ID}" =~ ^[0-9]{12}$ ]]; then
    printf 'CROSSPLANE_AWS_ACCOUNT_ID must be a 12-digit AWS account ID.\n' >&2
    exit 1
  fi
  : "${CROSSPLANE_AWS_RUNTIME_ROLE_ARN:=arn:aws:iam::${CROSSPLANE_AWS_ACCOUNT_ID}:role/provider-storage/crossplane}"
  validate_region CROSSPLANE_AWS_REGION "${CROSSPLANE_AWS_REGION}"
  if [[ ! "${CROSSPLANE_AWS_RUNTIME_ROLE_ARN}" =~ ^arn:aws:iam::${CROSSPLANE_AWS_ACCOUNT_ID}:role/.+[^/]$ ]]; then
    printf 'CROSSPLANE_AWS_RUNTIME_ROLE_ARN must be a role in CROSSPLANE_AWS_ACCOUNT_ID.\n' >&2
    exit 1
  fi
  if ! kube get secret/aws-provider-creds --namespace "${WORKSPACE_NAMESPACE}" >/dev/null 2>&1; then
    printf 'Secret %s/aws-provider-creds is missing. See tests/integration/README.md.\n' \
      "${WORKSPACE_NAMESPACE}" >&2
    exit 1
  fi

  bucket_name="$(aws_bucket_name)"
  apply_template \
    "${MANIFEST_DIR}/provider-configs/aws.yaml" \
    WORKSPACE_NAMESPACE "${WORKSPACE_NAMESPACE}" \
    AWS_RUNTIME_ROLE_ARN "${CROSSPLANE_AWS_RUNTIME_ROLE_ARN}"
  apply_template \
    "${MANIFEST_DIR}/environment-configs/storage-aws.yaml" \
    AWS_REGION "${CROSSPLANE_AWS_REGION}"
  apply_template \
    "${MANIFEST_DIR}/storages/aws.yaml" \
    AWS_BUCKET_NAME "${bucket_name}"
}

deploy_ovh() {
  local project_prefix region
  : "${CROSSPLANE_OVH_STORAGE_REGION:=de}"
  project_prefix="$(ovh_project_prefix)"
  region="${CROSSPLANE_OVH_STORAGE_REGION}"
  case "${region}" in
    de|gra) ;;
    *)
      printf 'CROSSPLANE_OVH_STORAGE_REGION must be de or gra.\n' >&2
      exit 1
      ;;
  esac
  if ! kube get secret/ovh-provider-creds --namespace "${WORKSPACE_NAMESPACE}" >/dev/null 2>&1; then
    printf 'Secret %s/ovh-provider-creds is missing. See tests/integration/README.md.\n' \
      "${WORKSPACE_NAMESPACE}" >&2
    exit 1
  fi

  apply_template \
    "${MANIFEST_DIR}/provider-configs/ovh.yaml" \
    WORKSPACE_NAMESPACE "${WORKSPACE_NAMESPACE}"
  apply_template \
    "${MANIFEST_DIR}/environment-configs/storage-ovh.yaml" \
    OVH_ENDPOINT "https://s3.${region}.io.cloud.ovh.net" \
    OVH_REGION "${region}" \
    OVH_PROJECT_ID "${CROSSPLANE_OVH_PROJECT_ID}"
  apply_template \
    "${MANIFEST_DIR}/storages/ovh.yaml" \
    OVH_PROJECT_PREFIX "${project_prefix}"
}

main() {
  require_cluster
  "deploy_${backend}"
  case "${backend}" in
    minio)
      wait_for_storage_secret s-jeff
      wait_for_storage_secret s-jane
      ;;
    aws)
      wait_for_storage_secret s-joe
      ;;
    ovh)
      wait_for_storage_secret s-john
      ;;
  esac
  kube get storages.pkg.internal --namespace "${WORKSPACE_NAMESPACE}"
}

main
