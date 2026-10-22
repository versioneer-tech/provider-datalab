#!/usr/bin/env bash
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

create_ingress_certificate() {
  local certificate private_key
  local result=0

  require_command openssl
  if kube get secret wildcard-tls --namespace "${WORKSPACE_NAMESPACE}" \
    -o jsonpath='{.data.tls\.crt}' 2>/dev/null | base64 --decode | \
    openssl x509 -checkend 300 -checkhost verify-data.lab.local -noout >/dev/null 2>&1; then
    return 0
  fi
  certificate="$(mktemp /tmp/datalab-data-cert.XXXXXX)"
  private_key="$(mktemp /tmp/datalab-data-key.XXXXXX)"
  openssl req -x509 -newkey rsa:2048 -nodes -days 1 \
    -subj '/CN=*.lab.local' \
    -addext 'subjectAltName=DNS:*.lab.local' \
    -keyout "${private_key}" -out "${certificate}" >/dev/null 2>&1 || result=$?
  if ((result == 0)); then
    kube create secret tls wildcard-tls \
      --namespace "${WORKSPACE_NAMESPACE}" \
      --cert "${certificate}" --key "${private_key}" \
      --dry-run=client -o yaml | kube apply -f - || result=$?
  fi
  rm -f "${certificate}" "${private_key}"
  return "${result}"
}

install_educates() {
  require_command helm
  install_kyverno
  create_ingress_certificate
  kube apply -f "${MANIFEST_DIR}/educates-rbac.yaml"
  if ! helm_release_matches educates "${EDUCATES_NAMESPACE}" "workspace-dependencies-educates-${EDUCATES_DEPENDENCIES_VERSION}"; then
    log "Installing Educates dependencies ${EDUCATES_DEPENDENCIES_VERSION}"
    helm_it upgrade --install educates \
      oci://ghcr.io/eoepca/workspace/workspace-dependencies-educates \
      --kubeconfig "${PROVIDER_DATALAB_KUBECONFIG}" \
      --kube-context "${KUBECTL_CONTEXT}" \
      --namespace "${EDUCATES_NAMESPACE}" --create-namespace \
      --version "${EDUCATES_DEPENDENCIES_VERSION}" \
      --set clusterIngressDomain=lab.local --set clusterIngressClass=nginx \
      --set tlsCertificateRef.name=wildcard-tls \
      --set tlsCertificateRef.namespace="${WORKSPACE_NAMESPACE}" --timeout 15m
  fi
  # Give controllers a CPU share under local load and time for cold starts.
  local controller
  for controller in secrets-manager session-manager; do
    kube patch "deployment/${controller}" --namespace "${EDUCATES_NAMESPACE}" \
      --type=strategic --patch '{"spec":{"template":{"spec":{"containers":[{
        "name":"operator",
        "resources":{"requests":{"cpu":"200m","memory":"128Mi"}},
        "startupProbe":{"failureThreshold":30,"timeoutSeconds":5},
        "livenessProbe":{"timeoutSeconds":5}
      }]}}}}'
  done
  kube rollout status deployment/secrets-manager --namespace "${EDUCATES_NAMESPACE}" --timeout=5m
  kube rollout status deployment/session-manager --namespace "${EDUCATES_NAMESPACE}" --timeout=5m
}

wait_for_runtime_namespace() {
  local datalab="$1"
  local deadline=$((SECONDS + 900))
  local namespace=""

  if ! kube wait \
    "object.kubernetes.m.crossplane.io/workshopenvironment-${datalab}" \
    --namespace "${WORKSPACE_NAMESPACE}" \
    --for=create --timeout=5m >/dev/null; then
    return 1
  fi
  if ! kube wait \
    "object.kubernetes.m.crossplane.io/workshopenvironment-${datalab}" \
    --namespace "${WORKSPACE_NAMESPACE}" \
    --for=condition=Ready --timeout=15m >/dev/null; then
    return 1
  fi

  until [[ -n "${namespace}" ]]; do
    namespace="$(kube get \
      "object.kubernetes.m.crossplane.io/workshopenvironment-${datalab}" \
      --namespace "${WORKSPACE_NAMESPACE}" \
      -o jsonpath='{.status.atProvider.manifest.status.educates.namespace}' \
      2>/dev/null || true)"
    if ((SECONDS >= deadline)); then
      printf 'The Educates runtime namespace for %s was not reported within 15 minutes.\n' \
        "${datalab}" >&2
      return 1
    fi
    [[ -n "${namespace}" ]] || sleep 5
  done
  printf '%s\n' "${namespace}"
}

