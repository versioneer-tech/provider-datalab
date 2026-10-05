#!/usr/bin/env bash
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

INTEGRATION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.bash
source "${INTEGRATION_DIR}/lib.bash"

: "${EDUCATES_DEPENDENCIES_VERSION:=2.2.1}"
: "${DATA_CLIENT_IMAGE:=curlimages/curl:8.10.1}"
: "${KEEP_DATA_RESOURCES:=0}"

readonly EDUCATES_NAMESPACE=educates
readonly ENABLED_DATALAB=verify-data-enabled
readonly DISABLED_DATALAB=verify-data-disabled
readonly ENABLED_STORAGE_SECRET=verify-data-enabled
readonly DISABLED_STORAGE_SECRET=verify-data-disabled
readonly PACKAGE_R_NAME=package-r
readonly PACKAGE_R_IMAGE=ghcr.io/versioneer-tech/package-r:vnext.1.1.0
readonly PACKAGE_R_ENDPOINT=http://default-hl.minio:9000
readonly PROBE_NAME=verify-data-health
readonly INVALID_ACCESS_KEY=xyz-invalid
readonly INVALID_ACCESS_KEY_B64=eHl6LWludmFsaWQ=
readonly MINIO_ACCESS_KEY=minioadmin
readonly MINIO_ACCESS_KEY_B64=bWluaW9hZG1pbg==

enabled_runtime_namespace=""
disabled_runtime_namespace=""

create_ingress_certificate() {
  local certificate private_key
  local result=0

  require_command openssl
  certificate="$(mktemp /tmp/provider-datalab-data-cert.XXXXXX)"
  private_key="$(mktemp /tmp/provider-datalab-data-key.XXXXXX)"
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

  log "Installing the EOEPCA+ Educates dependencies ${EDUCATES_DEPENDENCIES_VERSION}"
  helm_it upgrade --install educates \
    oci://ghcr.io/eoepca/workspace/workspace-dependencies-educates \
    --kubeconfig "${PROVIDER_DATALAB_KUBECONFIG}" \
    --kube-context "${KUBECTL_CONTEXT}" \
    --namespace "${EDUCATES_NAMESPACE}" \
    --create-namespace \
    --version "${EDUCATES_DEPENDENCIES_VERSION}" \
    --set clusterIngressDomain=lab.local \
    --set clusterIngressClass=nginx \
    --set tlsCertificateRef.name=wildcard-tls \
    --set tlsCertificateRef.namespace="${WORKSPACE_NAMESPACE}" \
    --wait \
    --timeout 15m

  kube rollout status deployment/secrets-manager \
    --namespace "${EDUCATES_NAMESPACE}" --timeout=5m
  kube rollout status deployment/session-manager \
    --namespace "${EDUCATES_NAMESPACE}" --timeout=5m
}

apply_data_datalabs() {
  log 'Applying the enabled and disabled data verification Datalabs'
  apply_template "${MANIFEST_DIR}/data/storage-secrets.yaml" \
    ENABLED_STORAGE_SECRET "${ENABLED_STORAGE_SECRET}" \
    DISABLED_STORAGE_SECRET "${DISABLED_STORAGE_SECRET}" \
    PACKAGE_R_ENDPOINT "${PACKAGE_R_ENDPOINT}" \
    WORKSPACE_NAMESPACE "${WORKSPACE_NAMESPACE}"
  apply_template "${MANIFEST_DIR}/data/datalabs.yaml" \
    ENABLED_DATALAB "${ENABLED_DATALAB}" \
    DISABLED_DATALAB "${DISABLED_DATALAB}" \
    WORKSPACE_NAMESPACE "${WORKSPACE_NAMESPACE}" \
    ENABLED_STORAGE_SECRET "${ENABLED_STORAGE_SECRET}" \
    DISABLED_STORAGE_SECRET "${DISABLED_STORAGE_SECRET}"
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

package_object_count() {
  local datalab="$1" kind="$2"

  kube get objects.kubernetes.m.crossplane.io \
    --namespace "${WORKSPACE_NAMESPACE}" \
    --selector "crossplane.io/composite=${datalab}" -o json | \
    jq --arg kind "${kind}" --arg name "${PACKAGE_R_NAME}" '
      [
        .items[]
        | select(.spec.forProvider.manifest.kind == $kind)
        | select(
            .spec.forProvider.manifest.metadata.labels["app.kubernetes.io/name"] == $name
          )
      ]
      | length
    '
}

package_object_manifest() {
  local datalab="$1" kind="$2" resource_name="${3:-${PACKAGE_R_NAME}}"

  kube get objects.kubernetes.m.crossplane.io \
    --namespace "${WORKSPACE_NAMESPACE}" \
    --selector "crossplane.io/composite=${datalab}" -o json | \
    jq --arg kind "${kind}" --arg name "${PACKAGE_R_NAME}" \
      --arg resource_name "${resource_name}" '
      [
        .items[]
        | select(.spec.forProvider.manifest.kind == $kind)
        | select(
            .spec.forProvider.manifest.metadata.labels["app.kubernetes.io/name"] == $name
          )
        | select(.spec.forProvider.manifest.metadata.name == $resource_name)
        | .spec.forProvider.manifest
      ]
      | if length == 1 then .[0] else error("expected one package-r object") end
    '
}

wait_for_package_objects() {
  local deadline=$((SECONDS + 300))
  local deployment_count service_count policy_count

  log 'Waiting for the shared package-r provider objects'
  while true; do
    deployment_count="$(package_object_count "${ENABLED_DATALAB}" Deployment)"
    service_count="$(package_object_count "${ENABLED_DATALAB}" Service)"
    policy_count="$(package_object_count "${ENABLED_DATALAB}" NetworkPolicy)"
    if [[ "${deployment_count}" == 1 && "${service_count}" == 1 && \
      "${policy_count}" == 2 ]]; then
      return
    fi
    if ((SECONDS >= deadline)); then
      printf 'The shared package-r objects were not rendered within five minutes.\n' >&2
      return 1
    fi
    sleep 5
  done
}

workshop_manifest() {
  local datalab="$1"

  kube get "object.kubernetes.m.crossplane.io/workshop-${datalab}" \
    --namespace "${WORKSPACE_NAMESPACE}" \
    -o json | jq '.spec.forProvider.manifest'
}

verify_deployment_contract() {
  local manifest

  manifest="$(package_object_manifest "${ENABLED_DATALAB}" Deployment)"
  if ! jq -e \
    --arg image "${PACKAGE_R_IMAGE}" \
    --arg name "${PACKAGE_R_NAME}" '
    .metadata.name == $name and
    .spec.replicas == 1 and
    .spec.strategy.type == "Recreate" and
    (.spec.template.metadata.annotations[
      "datalabs.pkg.internal/storage-secret-checksum"
    ] | test("^[0-9a-f]{64}$")) and
    (.spec.template.spec.containers | length == 1) and
    (.spec.template.spec.initContainers | length == 1) and
    ([.spec.template.spec.containers[] | select(.name == $name)] | length == 1) and
    ([.spec.template.spec.initContainers[]? | select(.image == $image)] | length == 1) and
    (
      [.spec.template.spec.initContainers[]?.command[]?,
       .spec.template.spec.initContainers[]?.args[]?]
      | join(" ")
      | contains("config init") and
        contains("--auth.method=proxy") and
        contains("--auth.header=X-Forwarded-Preferred-Username") and
        contains("users add default") and
        contains("users add datalab") and
        contains("shares add default public") and
        contains("--perm.create=true") and
        contains("--perm.rename=true") and
        contains("--perm.modify=true") and
        contains("--perm.delete=true")
    ) and
    (
      [.spec.template.spec.containers[] | select(.name == $name)][0] as $container
      | $container.image == $image and
        ($container.env | any(.name == "PACKAGE_R_DATABASE" and .value == "/state/package-r.db")) and
        ($container.env | any(.name == "PACKAGE_R_ADDRESS" and .value == "0.0.0.0")) and
        ($container.env | any(.name == "PACKAGE_R_PORT" and .value == "8888")) and
        ($container.env | any(.name == "PACKAGE_R_ROOT" and .value == "/")) and
        ($container.env | any(.name == "PACKAGE_R_BUCKETS")) and
        ($container.env | any(.name == "XDG_CACHE_HOME" and .value == "/cache")) and
        ($container.env | any(
          .name == "AWS_SESSION_TOKEN" and
          .valueFrom.secretKeyRef.optional == true
        )) and
        ($container.env | any(
          .name == "AWS_ENDPOINT_URL" and
          .valueFrom.secretKeyRef.key == "AWS_ENDPOINT_URL"
        )) and
        (all(
          ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_REGION", "AWS_ENDPOINT_URL"][];
          . as $variable | any($container.env[]; .name == $variable)
        )) and
        (all($container.env[];
          (.name | startswith("FB_") | not) and
          .name != "WORKSPACE" and
          .name != "AWS_S3_FORCE_PATH_STYLE")) and
        ($container.volumeMounts | any(.name == "state" and .mountPath == "/state")) and
        ($container.volumeMounts | any(.name == "cache" and .mountPath == "/cache")) and
        ($container.volumeMounts | any(.name == "tmp" and .mountPath == "/tmp")) and
        (all($container.volumeMounts[];
          .mountPath != "/workspace" and .mountPath != "/db")) and
        $container.startupProbe.httpGet.path == "/health" and
        $container.startupProbe.httpGet.port == "package-r" and
        $container.readinessProbe.httpGet.path == "/health" and
        $container.readinessProbe.httpGet.port == "package-r" and
        $container.livenessProbe.httpGet.path == "/health" and
        $container.livenessProbe.httpGet.port == "package-r"
    ) and
    (.spec.template.spec.volumes | any(.name == "state" and has("emptyDir"))) and
    (.spec.template.spec.volumes | any(.name == "cache" and has("emptyDir"))) and
    (.spec.template.spec.volumes | any(.name == "tmp" and has("emptyDir"))) and
    (all(.spec.template.spec.volumes[]; has("persistentVolumeClaim") | not))
  ' <<<"${manifest}" >/dev/null; then
    printf 'The shared package-r Deployment does not match the vnext contract.\n' >&2
    return 1
  fi
}

verify_service_contract() {
  local manifest

  manifest="$(package_object_manifest "${ENABLED_DATALAB}" Service)"
  if ! jq -e --arg name "${PACKAGE_R_NAME}" '
    .metadata.name == $name and
    .spec.type == "ClusterIP" and
    .spec.selector["app.kubernetes.io/name"] == $name and
    ([.spec.ports[]
      | select(.name == "http" and .port == 8888 and .targetPort == "package-r")]
      | length == 1)
  ' <<<"${manifest}" >/dev/null; then
    printf 'The shared package-r Service does not match the stable service contract.\n' >&2
    return 1
  fi
}

verify_network_policy_contract() {
  local manifest

  manifest="$(package_object_manifest \
    "${ENABLED_DATALAB}" NetworkPolicy "${PACKAGE_R_NAME}")"
  if ! jq -e --arg name "${PACKAGE_R_NAME}" '
    .metadata.name == $name and
    .spec.podSelector.matchLabels["app.kubernetes.io/name"] == $name and
    (.spec.policyTypes | index("Ingress") != null) and
    ([.spec.ingress[]?.from[]?
      | select(
          .podSelector.matchLabels["training.educates.dev/application"] == "workshop"
        )]
      | length > 0) and
    ([.spec.ingress[]?.ports[]?
      | select(.protocol == "TCP" and .port == 8888)]
      | length > 0)
  ' <<<"${manifest}" >/dev/null; then
    printf 'The package-r NetworkPolicy does not allow workshop ingress.\n' >&2
    return 1
  fi
}

verify_dns_network_policy_contract() {
  local manifest

  manifest="$(package_object_manifest \
    "${ENABLED_DATALAB}" NetworkPolicy "${PACKAGE_R_NAME}-dns")"
  if ! jq -e --arg name "${PACKAGE_R_NAME}-dns" '
    .metadata.name == $name and
    .spec.podSelector == {} and
    .spec.policyTypes == ["Egress"] and
    (.spec.egress | length == 1) and
    (.spec.egress[0].to | any(
      .namespaceSelector.matchLabels["kubernetes.io/metadata.name"] == "kube-system"
    )) and
    (.spec.egress[0].to | any(.ipBlock.cidr == "10.96.0.0/16")) and
    ([.spec.egress[0].ports[]? | [.protocol, .port]] | sort) ==
      ([ ["TCP", 53], ["UDP", 53] ] | sort)
  ' <<<"${manifest}" >/dev/null; then
    printf 'The package-r DNS NetworkPolicy does not restrict egress to DNS.\n' >&2
    return 1
  fi
}

verify_workshop_contract() {
  local datalab="$1" data_enabled="$2"
  local manifest

  manifest="$(workshop_manifest "${datalab}")"
  if ! jq -e --arg name "${PACKAGE_R_NAME}" '
    ([.. | objects
      | select(
          .kind? == "PersistentVolumeClaim" and
          .spec.storageClassName? == "csi-rclone"
        )]
      | length == 0) and
    ([.spec.session.objects[]?
      | select(
          (
            .kind == "Deployment" and
            any(.spec.template.spec.containers[]?;
              (.image | startswith("ghcr.io/versioneer-tech/package-r:")))
          ) or
          (
            .kind == "Service" and
            (
              .metadata.name == "data-$(session_name)" or
              .metadata.labels["app.kubernetes.io/name"]? == $name
            )
          )
        )]
      | length == 0)
  ' <<<"${manifest}" >/dev/null; then
    printf 'Workshop %s still owns package-r resources or a csi-rclone PVC.\n' \
      "${datalab}" >&2
    return 1
  fi

  if [[ "${data_enabled}" == true ]]; then
    if ! jq -e '
      [.spec.session.ingresses[]?
        | select(
            .name == "data" and
            .authentication.type == "session" and
            .protocol == "http" and
            .port == 8888 and
            .host == "package-r.$(workshop_namespace).svc.$(cluster_domain)" and
            any(.headers[]?;
              .name == "X-Package-R-User" and .value == "datalab")
          )]
      | length == 1
    ' <<<"${manifest}" >/dev/null; then
      printf 'Workshop %s does not route Data to the stable package-r Service.\n' \
        "${datalab}" >&2
      return 1
    fi
  elif ! jq -e '
    ([.spec.session.ingresses[]? | select(.name == "data")] | length == 0) and
    ([.spec.session.dashboards[]? | select(.name == "Data")] | length == 0)
  ' <<<"${manifest}" >/dev/null; then
    printf 'Data-disabled Workshop %s still exposes the Data application.\n' \
      "${datalab}" >&2
    return 1
  fi
}

verify_target_resources() {
  local namespace="$1"
  local deadline=$((SECONDS + 300))
  local kind count resource

  log 'Checking the provider-created package-r resources in the Educates namespace'
  for kind in deployments services networkpolicies; do
    while true; do
      count="$(kube get "${kind}" --namespace "${namespace}" \
        --selector "app.kubernetes.io/name=${PACKAGE_R_NAME}" \
        -o json 2>/dev/null | jq '.items | length' 2>/dev/null || true)"
      if [[ ("${kind}" == networkpolicies && "${count}" == 2) || \
        ("${kind}" != networkpolicies && "${count}" == 1) ]]; then
        break
      fi
      if ((SECONDS >= deadline)); then
        printf 'The expected package-r %s were not present in namespace %s; found %s.\n' \
          "${kind}" "${namespace}" "${count:-none}" >&2
        return 1
      fi
      sleep 5
    done
  done

  for resource in \
    deployment/package-r \
    service/package-r \
    networkpolicy/package-r \
    networkpolicy/package-r-dns; do
    if ! kube get "${resource}" \
      --namespace "${namespace}" -o json | \
      jq -e '
        all(.metadata.ownerReferences[]?;
          .kind != "WorkshopEnvironment" and .kind != "WorkshopSession")
      ' >/dev/null; then
      printf 'The package-r resource %s has an Educates controller owner.\n' \
        "${resource}" >&2
      return 1
    fi
  done

  if ! kube rollout status "deployment/${PACKAGE_R_NAME}" \
    --namespace "${namespace}" --timeout=10m; then
    printf 'The package-r Deployment did not become ready in namespace %s.\n' \
      "${namespace}" >&2
    return 1
  fi

  if ! kube get pvc --namespace "${namespace}" -o json | \
    jq -e 'all(.items[]; .spec.storageClassName != "csi-rclone")' >/dev/null; then
    printf 'Namespace %s contains a csi-rclone PVC.\n' "${namespace}" >&2
    return 1
  fi
}

verify_package_health() {
  local namespace="$1"
  local deadline=$((SECONDS + 300))
  local phase=""

  log 'Checking package-r health through the stable Service and ingress policy'
  kube delete "pod/${PROBE_NAME}" --namespace "${namespace}" \
    --ignore-not-found --wait=true
  if ! render_template "${MANIFEST_DIR}/data/client.yaml" \
    PROBE_NAME "${PROBE_NAME}" \
    PROBE_NAMESPACE "${namespace}" \
    CLIENT_IMAGE "${DATA_CLIENT_IMAGE}" | kube apply -f -; then
    return 1
  fi

  while true; do
    phase="$(kube get "pod/${PROBE_NAME}" --namespace "${namespace}" \
      -o jsonpath='{.status.phase}' 2>/dev/null || true)"
    case "${phase}" in
      Succeeded)
        kube logs "pod/${PROBE_NAME}" --namespace "${namespace}"
        return 0
        ;;
      Failed)
        kube logs "pod/${PROBE_NAME}" --namespace "${namespace}" || true
        kube describe "pod/${PROBE_NAME}" --namespace "${namespace}" || true
        return 1
        ;;
    esac
    if ((SECONDS >= deadline)); then
      printf 'The package-r health probe did not finish within five minutes.\n' >&2
      return 1
    fi
    sleep 5
  done
}

verify_no_direct_csi_pvc() {
  local datalab="$1"

  if ! kube get objects.kubernetes.m.crossplane.io \
    --namespace "${WORKSPACE_NAMESPACE}" \
    --selector "crossplane.io/composite=${datalab}" -o json | \
    jq -e '
      [.items[]
        | .spec.forProvider.manifest
        | select(
            .kind == "PersistentVolumeClaim" and
            .spec.storageClassName == "csi-rclone"
          )]
      | length == 0
    ' >/dev/null; then
    printf 'Datalab %s rendered a direct csi-rclone PVC.\n' "${datalab}" >&2
    return 1
  fi
}

verify_provider_object_ownership() {
  if ! kube get objects.kubernetes.m.crossplane.io \
    --namespace "${WORKSPACE_NAMESPACE}" \
    --selector "crossplane.io/composite=${ENABLED_DATALAB}" -o json | \
    jq -e \
      --arg datalab "${ENABLED_DATALAB}" \
      --arg name "${PACKAGE_R_NAME}" \
      --arg namespace "${enabled_runtime_namespace}" '
      [.items[]
        | select(
            .spec.forProvider.manifest.metadata.labels["app.kubernetes.io/name"] == $name
          )] as $objects
      | ($objects | length == 4) and
        (($objects | map(.metadata.name) | sort) ==
          ([
            "data-deployment-\($datalab)",
            "data-dns-networkpolicy-\($datalab)",
            "data-networkpolicy-\($datalab)",
            "data-service-\($datalab)"
          ] | sort)) and
        all($objects[];
          .spec.forProvider.manifest.metadata.namespace == $namespace
        ) and
        all($objects[];
          any(.metadata.ownerReferences[]?;
            .kind == "Datalab" and
            .name == $datalab and
            .controller == true
          )
        )
    ' >/dev/null; then
    printf 'The package-r provider objects are not owned by Datalab %s.\n' \
      "${ENABLED_DATALAB}" >&2
    return 1
  fi
}

verify_runtime_secret_observer() {
  local observer="observe-runtime-storage-secret-${ENABLED_DATALAB}"

  if ! kube get "object.kubernetes.m.crossplane.io/${observer}" \
    --namespace "${WORKSPACE_NAMESPACE}" -o json | \
    jq -e \
      --arg datalab "${ENABLED_DATALAB}" \
      --arg namespace "${enabled_runtime_namespace}" '
      .spec.managementPolicies == ["Observe"] and
      .spec.watch == true and
      .spec.forProvider.manifest.kind == "Secret" and
      .spec.forProvider.manifest.metadata.name == "\($datalab)-datalab" and
      .spec.forProvider.manifest.metadata.namespace == $namespace and
      any(.metadata.ownerReferences[]?;
        .kind == "Datalab" and
        .name == $datalab and
        .controller == true
      )
    ' >/dev/null; then
    printf 'The runtime storage Secret observer is not configured safely.\n' >&2
    return 1
  fi
}

deployment_checksum() {
  local namespace="$1"

  kube get "deployment/${PACKAGE_R_NAME}" --namespace "${namespace}" -o json | \
    jq -r '.spec.template.metadata.annotations[
      "datalabs.pkg.internal/storage-secret-checksum"
    ] // ""'
}

package_pod_uid() {
  local namespace="$1"

  kube get pods --namespace "${namespace}" \
    --selector "app.kubernetes.io/name=${PACKAGE_R_NAME}" -o json | \
    jq -r '.items[0].metadata.uid // ""'
}

wait_for_runtime_access_key() {
  local namespace="$1" expected="$2"
  local deadline=$((SECONDS + 600))
  local actual=""

  while true; do
    actual="$(kube get "secret/${ENABLED_DATALAB}-datalab" \
      --namespace "${namespace}" \
      -o jsonpath='{.data.AWS_ACCESS_KEY_ID}' 2>/dev/null || true)"
    if [[ "${actual}" == "${expected}" ]]; then
      return
    fi
    if ((SECONDS >= deadline)); then
      printf 'The runtime storage Secret did not receive the credential update.\n' >&2
      return 1
    fi
    sleep 5
  done
}

wait_for_deployment_rotation() {
  local namespace="$1" previous_checksum="$2" previous_pod_uid="$3"
  local deadline=$((SECONDS + 600))
  local checksum="" pod_uid=""

  while true; do
    checksum="$(deployment_checksum "${namespace}" 2>/dev/null || true)"
    pod_uid="$(package_pod_uid "${namespace}" 2>/dev/null || true)"
    if [[ -n "${checksum}" && "${checksum}" != "${previous_checksum}" && \
      -n "${pod_uid}" && "${pod_uid}" != "${previous_pod_uid}" ]]; then
      kube rollout status "deployment/${PACKAGE_R_NAME}" \
        --namespace "${namespace}" --timeout=10m
      return
    fi
    if ((SECONDS >= deadline)); then
      printf 'The package-r Deployment did not rotate with its storage Secret.\n' >&2
      return 1
    fi
    sleep 5
  done
}

patch_source_access_key() {
  local value="$1"

  kube patch "secret/${ENABLED_STORAGE_SECRET}" \
    --namespace "${WORKSPACE_NAMESPACE}" --type=merge \
    --patch "{\"stringData\":{\"AWS_ACCESS_KEY_ID\":\"${value}\"}}" >/dev/null
}

verify_credential_rotation() {
  local namespace="$1"
  local initial_checksum initial_pod_uid invalid_checksum invalid_pod_uid
  local result=0 transitioned=false

  initial_checksum="$(deployment_checksum "${namespace}")"
  initial_pod_uid="$(package_pod_uid "${namespace}")"
  if [[ ! "${initial_checksum}" =~ ^[[:xdigit:]]{64}$ || \
    -z "${initial_pod_uid}" ]]; then
    printf 'The package-r Deployment has no valid credential rollout marker.\n' >&2
    return 1
  fi

  log 'Checking package-r credential rotation'
  if ! patch_source_access_key "${INVALID_ACCESS_KEY}"; then
    return 1
  fi
  if wait_for_runtime_access_key "${namespace}" "${INVALID_ACCESS_KEY_B64}" && \
    wait_for_deployment_rotation \
      "${namespace}" "${initial_checksum}" "${initial_pod_uid}"; then
    transitioned=true
    invalid_checksum="$(deployment_checksum "${namespace}")"
    invalid_pod_uid="$(package_pod_uid "${namespace}")"
  else
    result=1
  fi

  if ! patch_source_access_key "${MINIO_ACCESS_KEY}" || \
    ! wait_for_runtime_access_key "${namespace}" "${MINIO_ACCESS_KEY_B64}"; then
    return 1
  fi
  if [[ "${transitioned}" == true ]] && ! wait_for_deployment_rotation \
    "${namespace}" "${invalid_checksum}" "${invalid_pod_uid}"; then
    result=1
  fi

  return "${result}"
}

verify_no_target_resources() {
  local namespace="$1"
  local kind count

  for kind in deployments services networkpolicies; do
    count="$(kube get "${kind}" --namespace "${namespace}" \
      --selector "app.kubernetes.io/name=${PACKAGE_R_NAME}" \
      -o json | jq '.items | length')"
    if [[ "${count}" != 0 ]]; then
      printf 'Data-disabled namespace %s contains %s package-r %s.\n' \
        "${namespace}" "${count}" "${kind}" >&2
      return 1
    fi
  done
}

verify_disabled_contract() {
  local kind count

  log 'Checking that data.enabled=false emits no package-r resources'
  for kind in Deployment Service NetworkPolicy; do
    count="$(package_object_count "${DISABLED_DATALAB}" "${kind}")"
    if [[ "${count}" != 0 ]]; then
      printf 'Data-disabled Datalab %s rendered %s package-r %s object(s).\n' \
        "${DISABLED_DATALAB}" "${count}" "${kind}" >&2
      return 1
    fi
  done
  verify_no_direct_csi_pvc "${DISABLED_DATALAB}"
  verify_workshop_contract "${DISABLED_DATALAB}" false
}

show_data_diagnostics() {
  kube get \
    "datalab.pkg.internal/${ENABLED_DATALAB}" \
    "datalab.pkg.internal/${DISABLED_DATALAB}" \
    --namespace "${WORKSPACE_NAMESPACE}" -o wide || true
  kube get objects.kubernetes.m.crossplane.io \
    --namespace "${WORKSPACE_NAMESPACE}" \
    --selector "crossplane.io/composite=${ENABLED_DATALAB}" || true
  kube get objects.kubernetes.m.crossplane.io \
    --namespace "${WORKSPACE_NAMESPACE}" \
    --selector "crossplane.io/composite=${DISABLED_DATALAB}" || true
  if [[ -n "${enabled_runtime_namespace}" ]]; then
    kube get deployment,service,networkpolicy,pod,pvc \
      --namespace "${enabled_runtime_namespace}" || true
    kube get events --namespace "${enabled_runtime_namespace}" \
      --sort-by=.lastTimestamp || true
  fi
}

cleanup_successful_verification() {
  if [[ "${KEEP_DATA_RESOURCES}" == 1 ]]; then
    return
  fi

  if [[ -n "${enabled_runtime_namespace}" ]]; then
    kube delete "pod/${PROBE_NAME}" --namespace "${enabled_runtime_namespace}" \
      --ignore-not-found --wait=true
  fi
  kube delete \
    "datalab.pkg.internal/${ENABLED_DATALAB}" \
    "datalab.pkg.internal/${DISABLED_DATALAB}" \
    --namespace "${WORKSPACE_NAMESPACE}" --ignore-not-found --wait=false
  if kube wait \
    "datalab.pkg.internal/${ENABLED_DATALAB}" \
    "datalab.pkg.internal/${DISABLED_DATALAB}" \
    --namespace "${WORKSPACE_NAMESPACE}" --for=delete --timeout=10m; then
    kube delete secret \
      "${ENABLED_STORAGE_SECRET}" "${DISABLED_STORAGE_SECRET}" \
      --namespace "${WORKSPACE_NAMESPACE}" --ignore-not-found --wait=true
  else
    printf 'Data verification cleanup is still running; resources were kept for diagnosis.\n' >&2
  fi
}

main() {
  require_cluster
  require_command jq
  install_educates
  apply_data_datalabs

  if ! enabled_runtime_namespace="$(wait_for_runtime_namespace "${ENABLED_DATALAB}")" ||
    ! disabled_runtime_namespace="$(wait_for_runtime_namespace "${DISABLED_DATALAB}")" ||
    ! wait_for_package_objects ||
    ! verify_deployment_contract ||
    ! verify_service_contract ||
    ! verify_network_policy_contract ||
    ! verify_dns_network_policy_contract ||
    ! verify_provider_object_ownership ||
    ! verify_runtime_secret_observer ||
    ! verify_no_direct_csi_pvc "${ENABLED_DATALAB}" ||
    ! verify_workshop_contract "${ENABLED_DATALAB}" true ||
    ! verify_target_resources "${enabled_runtime_namespace}" ||
    ! verify_credential_rotation "${enabled_runtime_namespace}" ||
    ! verify_package_health "${enabled_runtime_namespace}" ||
    ! verify_disabled_contract ||
    ! verify_no_target_resources "${disabled_runtime_namespace}"; then
    show_data_diagnostics
    printf 'Data verification resources were kept for diagnosis.\n' >&2
    exit 1
  fi

  cleanup_successful_verification
}

main "$@"
