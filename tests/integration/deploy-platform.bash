#!/usr/bin/env bash
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

INTEGRATION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.bash
source "${INTEGRATION_DIR}/lib.bash"
source "${INTEGRATION_DIR}/runtime.bash"

install_crossplane() {
  require_command helm
  if helm_release_matches crossplane "${CROSSPLANE_NAMESPACE}" "crossplane-${CROSSPLANE_VERSION}"; then
    kube rollout status deployment/crossplane --namespace "${CROSSPLANE_NAMESPACE}" --timeout=5m
    return
  fi
  log "Installing Crossplane ${CROSSPLANE_VERSION}"
  helm_it repo add crossplane-stable https://charts.crossplane.io/stable --force-update
  helm_it repo update crossplane-stable
  helm_it upgrade --install crossplane crossplane-stable/crossplane \
    --kubeconfig "${PROVIDER_DATALAB_KUBECONFIG}" \
    --kube-context "${KUBECTL_CONTEXT}" \
    --namespace "${CROSSPLANE_NAMESPACE}" \
    --create-namespace \
    --version "${CROSSPLANE_VERSION}" \
    --set 'provider.defaultActivations={}' \
    --wait \
    --timeout 10m
}

install_datalab() {
  log 'Installing Provider Datalab dependencies and source manifests'
  kube apply -f "${REPO_ROOT}/dependencies/00-mrap.yaml"
  kube apply -f "${REPO_ROOT}/dependencies/01-deploymentRuntimeConfigs.yaml"
  kube apply -f "${REPO_ROOT}/dependencies/02-providers.yaml"
  kube apply -f "${REPO_ROOT}/dependencies/functions.yaml"
  kube apply -f "${REPO_ROOT}/dependencies/rbac.yaml"
  wait_for_provider_runtime provider-keycloak
  wait_for_crd_established protocolmappers.client.keycloak.m.crossplane.io
  wait_for_provider_runtime provider-kubernetes
  kube apply -f "${REPO_ROOT}/dependencies/03-providerConfigs.yaml"
  kube apply -f "${REPO_ROOT}/xrd.yaml"
  wait_for_crd_established datalabs.versioneer.at
  python3 - "${REPO_ROOT}/xrd.yaml" "${PROVIDER_DATALAB_KUBECONFIG}" "${KUBECTL_CONTEXT}" <<'DEFINITION'
import json
from pathlib import Path
import subprocess
import sys
import time
import yaml

expected = yaml.safe_load(Path(sys.argv[1]).read_text())["spec"]["versions"]

def contains(expected, actual):
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and contains(value, actual[key]) for key, value in expected.items()
        )
    return expected == actual

deadline = time.monotonic() + 120
while True:
    result = subprocess.run(
        ["kubectl", "--kubeconfig", sys.argv[2], "--context", sys.argv[3],
         "get", "crd/datalabs.versioneer.at", "-o", "json"],
        capture_output=True, text=True, check=True,
    )
    actual = {version["name"]: version for version in json.loads(result.stdout)["spec"]["versions"]}
    if all(
        version["name"] in actual and contains(
            version["schema"]["openAPIV3Schema"]["properties"],
            actual[version["name"]]["schema"]["openAPIV3Schema"]["properties"],
        ) for version in expected
    ):
        print("PASS generated Datalab CRD matches the current XRD schema")
        break
    if time.monotonic() >= deadline:
        raise SystemExit("The Datalab CRD schema is stale. Inspect the XRD events for validation errors.")
    time.sleep(2)
DEFINITION
  local composition_directory
  composition_directory="$(mktemp -d /tmp/datalab-it-composition.XXXXXX)"
  python3 "${REPO_ROOT}/scripts/build-composition.py" --response-ttl 1m \
    --output "${composition_directory}/composition.yaml"
  # Client-side apply stores this large Composition in an annotation.
  kube apply --server-side --field-manager=provider-datalab-integration \
    -f "${composition_directory}/composition.yaml"
  rm -rf "${composition_directory}"
  kube apply -f "${MANIFEST_DIR}/environment-configs/datalabs.yaml"
}

wait_for_packages() {
  local name
  for name in \
    crossplane-contrib-function-python \
    crossplane-contrib-function-auto-ready; do
    kube wait "function.pkg.crossplane.io/${name}" \
      --for=condition=Healthy --timeout=15m
  done
}

main() {
  require_cluster

  kube apply -f "${MANIFEST_DIR}/namespaces.yaml"
  create_ingress_certificate
  install_crossplane
  install_datalab
  kube apply -f "${MANIFEST_DIR}/provider-configs/kubernetes.yaml"

  kube apply -f "${MANIFEST_DIR}/minio.yaml"
  kube apply -f "${MANIFEST_DIR}/storage-secrets.yaml"
  kube rollout status deployment/default --namespace minio --timeout=5m
  wait_for_packages
  park_unused_operators
  resource_budget
  kube get providers.pkg.crossplane.io,functions.pkg.crossplane.io
}

main "$@"
