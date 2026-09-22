#!/usr/bin/env bash
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

INTEGRATION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.bash
source "${INTEGRATION_DIR}/lib.bash"

require_command kind
require_command kubectl

if ! kind_cluster_exists; then
  printf 'The dedicated Kind cluster was not created; no cluster diagnostics are available.\n'
  exit 0
fi

require_cluster

kube get providers.pkg.crossplane.io,functions.pkg.crossplane.io,configurations.pkg.crossplane.io || true
kube get storages.pkg.internal --all-namespaces || true
kube get networkpolicies.networking.k8s.io --all-namespaces || true
kube get validatingpolicies.policies.kyverno.io || true
kube get pods --all-namespaces -o wide || true
kube get events --all-namespaces --sort-by=.lastTimestamp || true
