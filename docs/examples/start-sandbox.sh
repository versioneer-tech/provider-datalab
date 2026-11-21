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

pvc_uid="$("${kube[@]}" get "persistentvolumeclaim/${sandbox_pvc}" -o jsonpath='{.metadata.uid}')"
[[ -n "${pvc_uid}" ]] || { printf 'The session PVC has no UID.\n' >&2; exit 1; }
sandbox="$("${kube[@]}" get "sandbox.agents.x-k8s.io/${sandbox_name}" --ignore-not-found -o json)"
if [[ -z "${sandbox}" ]]; then
  manifest="$("${kube[@]}" get sandboxtemplate.extensions.agents.x-k8s.io/sandboxd -o json |
  jq --arg name "${sandbox_name}" --arg namespace "${sandbox_namespace}" --arg pvc "${sandbox_pvc}" '
    {
      apiVersion: "agents.x-k8s.io/v1beta1",
      kind: "Sandbox",
      metadata: {name: $name, namespace: $namespace, labels: {"datalabs.versioneer.at/session": $name}},
      spec: {operatingMode: "Running", service: false, podTemplate: .spec.podTemplate}
    }
    | .spec.podTemplate.spec.volumes = (
        [(.spec.podTemplate.spec.volumes // [])[] | select(.name != "workspace")]
        + [{name: "workspace", persistentVolumeClaim: {claimName: $pvc}}]
      )
  ' | jq --arg uid "${pvc_uid}" '.metadata.annotations = {"datalabs.versioneer.at/session-pvc-uid": $uid}')"
  if ! sandbox="$(printf '%s\n' "${manifest}" | "${kube[@]}" create -f - -o json)"; then
    # Another client can create the Sandbox after the first read.
    sandbox="$("${kube[@]}" get "sandbox.agents.x-k8s.io/${sandbox_name}" -o json)"
  fi
fi

if ! jq -e --arg name "${sandbox_name}" --arg pvc "${sandbox_pvc}" --arg uid "${pvc_uid}" '
  .metadata.labels["datalabs.versioneer.at/session"] == $name and
  .metadata.annotations["datalabs.versioneer.at/session-pvc-uid"] == $uid and
  ((.metadata.ownerReferences // []) | length == 0) and
  (.metadata.deletionTimestamp == null) and
  ((.spec.volumeClaimTemplates // []) | length == 0) and
  any(.spec.podTemplate.spec.volumes[]?; .name == "workspace" and .persistentVolumeClaim.claimName == $pvc) and
  any(.spec.podTemplate.spec.containers[]?.volumeMounts[]?; .name == "workspace" and .mountPath == "/workspace")
' <<<"${sandbox}" >/dev/null; then
  printf 'Refusing to use a Sandbox with another owner or session PVC binding.\n' >&2
  exit 1
fi
sandbox_uid="$(jq -er '.metadata.uid' <<<"${sandbox}")"
if [[ "$(jq -r '.spec.operatingMode // "Running"' <<<"${sandbox}")" != Running ]]; then
  "${kube[@]}" patch "sandbox.agents.x-k8s.io/${sandbox_name}" --type=json --patch "$(
    jq -cn --arg uid "${sandbox_uid}" --arg version "$(jq -er '.metadata.resourceVersion' <<<"${sandbox}")" '
      [{op:"test",path:"/metadata/uid",value:$uid},
       {op:"test",path:"/metadata/resourceVersion",value:$version},
       {op:"add",path:"/spec/operatingMode",value:"Running"}]'
  )"
fi

deadline=$((SECONDS + 300))
while :; do
  sandbox="$("${kube[@]}" get "sandbox.agents.x-k8s.io/${sandbox_name}" -o json)"
  [[ "$(jq -er '.metadata.uid' <<<"${sandbox}")" == "${sandbox_uid}" ]] || {
    printf 'The Sandbox was replaced while waiting for readiness.\n' >&2; exit 1;
  }
  if jq -e '.metadata.generation as $generation |
    (.spec.operatingMode // "Running") == "Running" and
    any(.status.conditions[]?; .type == "Ready" and .status == "True" and .observedGeneration == $generation)
  ' <<<"${sandbox}" >/dev/null; then
    break
  fi
  ((SECONDS < deadline)) || { printf 'The Sandbox did not become ready.\n' >&2; exit 1; }
  sleep 3
done
"${kube[@]}" get "pod/${sandbox_name}" "persistentvolumeclaim/${sandbox_pvc}"
printf '\nSandbox is ready. Start the local connection:\n'
printf '%q ' "${kube[@]}" port-forward --address 127.0.0.1 "pod/${sandbox_name}" 18080:8080 19090:9090
printf '\n'
