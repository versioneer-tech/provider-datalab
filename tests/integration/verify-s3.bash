#!/usr/bin/env bash
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

set -Eeuo pipefail

INTEGRATION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.bash
source "${INTEGRATION_DIR}/lib.bash"
# shellcheck source=educates.bash
source "${INTEGRATION_DIR}/educates.bash"

: "${EDUCATES_DEPENDENCIES_VERSION:=2.2.1}"
: "${KEEP_S3_RESOURCES:=0}"
readonly EDUCATES_NAMESPACE=educates
readonly S3_DATALAB=verify-s3
readonly CONTOUR_VERSION=v1.33.7
runtime_namespace=""
client_image=""
work_directory="$(mktemp -d /tmp/datalab-s3.XXXXXX)"

cleanup_local() {
  rm -rf "${work_directory}"
}
trap cleanup_local EXIT

show_s3_diagnostics() {
  kube get datalab "${S3_DATALAB}" --namespace workspace || true
  kube get objects.kubernetes.m.crossplane.io --namespace workspace \
    --selector "crossplane.io/composite=${S3_DATALAB}" || true
  kube get pods --namespace keycloak || true
  kube get gateway --namespace projectcontour || true
  if [[ -n "${runtime_namespace}" ]]; then
    kube get pods,httproutes,services,networkpolicies --namespace "${runtime_namespace}" || true
    kube get events --namespace "${runtime_namespace}" --sort-by=.lastTimestamp | tail -30 || true
    kube logs deployment/data-s3 --namespace "${runtime_namespace}" --all-containers --tail=30 || true
  fi
}

report_s3_failure() {
  local result=$?
  trap - ERR
  show_s3_diagnostics
  printf 'S3 verification resources were kept for diagnosis.\n' >&2
  exit "${result}"
}
trap report_s3_failure ERR

install_s3_prerequisites() {
  install_educates
  log 'Checking the Contour Gateway provisioner and Keycloak test realm'
  local contour_manifest="${PROVIDER_DATALAB_HELM_HOME}/contour-${CONTOUR_VERSION}.yaml"
  mkdir -p "${PROVIDER_DATALAB_HELM_HOME}"
  if [[ ! -s "${contour_manifest}" ]]; then
    curl --fail --silent --show-error --location \
      "https://raw.githubusercontent.com/projectcontour/contour/${CONTOUR_VERSION}/examples/render/contour-gateway-provisioner.yaml" \
      --output "${work_directory}/contour.yaml"
    mv "${work_directory}/contour.yaml" "${contour_manifest}"
  fi
  kube apply --server-side -f "${contour_manifest}"
  wait_for_crd_established gateways.gateway.networking.k8s.io
  kube rollout status deployment/contour-gateway-provisioner --namespace projectcontour --timeout=10m
  kube apply -f "${MANIFEST_DIR}/s3/gateway.yaml"
  kube apply -f "${MANIFEST_DIR}/s3/keycloak.yaml"
  kube rollout status deployment/keycloak --namespace keycloak --timeout=10m
  kube wait gateway/verify-s3 --namespace projectcontour --for=condition=Programmed --timeout=10m
  kube wait deployment --namespace projectcontour --selector gateway.networking.k8s.io/gateway-name=verify-s3 \
    --for=condition=Available --timeout=10m
  kube apply -f "${MANIFEST_DIR}/s3/environmentconfig.yaml"
}

build_client() {
  local digest
  digest="$(cat "${REPO_ROOT}/tests/s3/"{Dockerfile,s3-credentials.py,e2e.py} | sha256sum | cut -c1-16)"
  client_image="verify-s3-client:${digest}"
  mkdir -p "${work_directory}/docker"
  if ! DOCKER_CONFIG="${work_directory}/docker" docker image inspect "${client_image}" >/dev/null 2>&1; then
    log 'Building the S3 SDK test client'
    mkdir -p "${work_directory}/build/tests/s3"
    cp "${REPO_ROOT}/tests/s3/"{s3-credentials.py,e2e.py} "${work_directory}/build/tests/s3/"
    DOCKER_CONFIG="${work_directory}/docker" docker build --provenance=false --tag "${client_image}" \
      --file "${REPO_ROOT}/tests/s3/Dockerfile" "${work_directory}/build"
  fi
  if ! docker exec "${KIND_CLUSTER_NAME}-control-plane" crictl inspecti "docker.io/library/${client_image}" >/dev/null 2>&1; then
    DOCKER_CONFIG="${work_directory}/docker" KUBECONFIG="${PROVIDER_DATALAB_KUBECONFIG}" \
      kind load docker-image "${client_image}" --name "${KIND_CLUSTER_NAME}"
  fi
}

verify_s3() {
  local gateway_service gateway_ip certificate
  kube apply -f "${MANIFEST_DIR}/s3/datalab.yaml"
  runtime_namespace="$(wait_for_runtime_namespace "${S3_DATALAB}")"
  # Wait for the composed resources before starting the client.
  kube wait deployment/data-s3 --namespace "${runtime_namespace}" --for=create --timeout=10m
  kube rollout status deployment/data-s3 --namespace "${runtime_namespace}" --timeout=10m
  kube wait deployment/package-r --namespace "${runtime_namespace}" --for=create --timeout=10m
  kube rollout status deployment/package-r --namespace "${runtime_namespace}" --timeout=10m
  kube wait datalab/verify-s3 --namespace workspace --for=condition=Ready --timeout=10m

  gateway_service="$(kube get services --namespace projectcontour \
    --selector gateway.networking.k8s.io/gateway-name=verify-s3 -o json | \
    jq -er '[.items[] | select(any(.spec.ports[]; .port == 443)) | .metadata.name] |
      if length == 1 then .[0] else error("Expected one HTTPS Gateway Service") end')"
  [[ -n "${gateway_service}" ]]
  gateway_ip="$(kube get service "${gateway_service}" --namespace projectcontour -o jsonpath='{.spec.clusterIP}')"
  certificate="${work_directory}/tls.crt"
  kube get secret wildcard-tls --namespace workspace -o jsonpath='{.data.tls\.crt}' | base64 --decode >"${certificate}"
  kube create configmap verify-s3-ca --namespace "${runtime_namespace}" --from-file="tls.crt=${certificate}" \
    --dry-run=client -o yaml | kube apply -f -
  kube delete pod verify-s3-client --namespace "${runtime_namespace}" --ignore-not-found --wait=true
  render_template "${MANIFEST_DIR}/s3/client.yaml" \
    RUNTIME_NAMESPACE "${runtime_namespace}" GATEWAY_IP "${gateway_ip}" \
    S3_CLIENT_IMAGE "${client_image}" \
    >"${work_directory}/client.yaml"
  # Retain the last concrete manifest in a cluster ConfigMap for diagnosis.
  kube create configmap verify-s3-client-manifest --namespace "${runtime_namespace}" \
    --from-file="client.yaml=${work_directory}/client.yaml" --dry-run=client -o yaml | kube apply -f -
  kube apply -f "${work_directory}/client.yaml"
  kube wait pod/verify-s3-client --namespace "${runtime_namespace}" --for=condition=Ready --timeout=5m
  kube exec verify-s3-client --namespace "${runtime_namespace}" -- python -u /test/e2e.py

  log 'Disabling environment S3 and checking browser-only Gateway exposure'
  kube patch environmentconfig datalab-s3-it --type=merge \
    --patch '{"data":{"httpRoute":{"enableS3":false}}}'
  kube wait deployment/data-s3 --namespace "${runtime_namespace}" --for=delete --timeout=5m
  local deadline=$((SECONDS + 120))
  until kube get httproute/data --namespace "${runtime_namespace}" -o json | jq -e '
    (.spec.rules | length == 1) and
    (.spec.rules[0].backendRefs[0].name == "package-r") and
    (.spec.rules[0].backendRefs[0].port == 4180)
  ' >/dev/null; do
    ((SECONDS < deadline)) || return 1
    sleep 2
  done
  kube wait datalab/verify-s3 --namespace workspace --for=condition=Ready --timeout=5m
  [[ "$(kube get ingresses --namespace "${runtime_namespace}" -o json | jq '.items | length')" == 0 ]]
  kube exec verify-s3-client --namespace "${runtime_namespace}" -- python -u /test/e2e.py --browser-only
}

main() {
  require_cluster
  require_command jq
  require_command docker
  require_command openssl
  build_client
  install_s3_prerequisites
  verify_s3
  if [[ "${KEEP_S3_RESOURCES}" != 1 ]]; then
    kube delete datalab/verify-s3 --namespace workspace --wait=false
    kube wait datalab/verify-s3 --namespace workspace --for=delete --timeout=10m
    kube delete secret/verify-s3 --namespace workspace --ignore-not-found
  fi
}

main "$@"
