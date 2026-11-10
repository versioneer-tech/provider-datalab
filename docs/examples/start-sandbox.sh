#!/usr/bin/env bash
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

if [[ $# != 5 ]]; then
  printf 'Usage: bash %s KUBECONFIG CONTEXT NAMESPACE SANDBOX PVC\n' "$0" >&2
  exit 2
fi
for tool in kubectl jq; do
  command -v "${tool}" >/dev/null || { printf 'Install %s first.\n' "${tool}" >&2; exit 1; }
done

sandbox_kubeconfig=$1
sandbox_context=$2
sandbox_namespace=$3
sandbox_name=$4
sandbox_pvc=$5
kube=(kubectl --kubeconfig "${sandbox_kubeconfig}" --context "${sandbox_context}" --namespace "${sandbox_namespace}")

"${kube[@]}" get "persistentvolumeclaim/${sandbox_pvc}"
"${kube[@]}" get sandboxtemplate.extensions.agents.x-k8s.io/sandboxd -o json |
  jq --arg name "${sandbox_name}" --arg namespace "${sandbox_namespace}" --arg pvc "${sandbox_pvc}" '
    {
      apiVersion: "agents.x-k8s.io/v1beta1",
      kind: "Sandbox",
      metadata: {name: $name, namespace: $namespace},
      spec: {podTemplate: .spec.podTemplate}
    }
    | .spec.podTemplate.spec.volumes = (
        [(.spec.podTemplate.spec.volumes // [])[] | select(.name != "workspace")]
        + [{name: "workspace", persistentVolumeClaim: {claimName: $pvc}}]
      )
  ' | "${kube[@]}" create -f -

"${kube[@]}" wait "sandbox.agents.x-k8s.io/${sandbox_name}" --for=condition=Ready --timeout=5m
"${kube[@]}" get "pod/${sandbox_name}" "persistentvolumeclaim/${sandbox_pvc}"
printf '\nSandbox is ready. Start the local connection:\n'
printf '%q ' "${kube[@]}" port-forward --address 127.0.0.1 "pod/${sandbox_name}" 18080:8080 19090:9090
printf '\n'
