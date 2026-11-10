#!/usr/bin/env bash
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

create_ingress_certificate() {
  local certificate private_key
  local result=0

  require_command openssl
  certificate="$(mktemp /tmp/datalab-data-cert.XXXXXX)"
  private_key="$(mktemp /tmp/datalab-data-key.XXXXXX)"
  openssl req -x509 -newkey rsa:2048 -nodes -days 1 \
    -subj '/CN=*.lab.acme.com' \
    -addext 'subjectAltName=DNS:*.lab.acme.com' \
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

wait_for_runtime_namespace() {
  local datalab="$1"
  kube wait "namespace/${datalab}" --for=create --timeout=5m >/dev/null || return 1
  kube wait "object.kubernetes.m.crossplane.io/namespace-${datalab}" \
    --namespace "${WORKSPACE_NAMESPACE}" --for=condition=Ready --timeout=5m >/dev/null || return 1
  printf '%s\n' "${datalab}"
}
