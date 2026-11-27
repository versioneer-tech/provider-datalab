#!/usr/bin/env bash
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

set -Eeuo pipefail
INTEGRATION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${INTEGRATION_DIR}/lib.bash"
source "${INTEGRATION_DIR}/runtime.bash"
source "${INTEGRATION_DIR}/postgres.bash"
source "${INTEGRATION_DIR}/snapshots.bash"
: "${KEEP_VCLUSTER_RESOURCES:=0}"
snapshots_enabled=0
readonly VCLUSTER_NAMESPACE=verify-vcluster
work_directory="$(mktemp -d /tmp/datalab-vcluster.XXXXXX)"
trap 'rm -rf "${work_directory}"' EXIT

report_failure() {
  local result=$?
  trap - ERR
  kube get datalabs.versioneer.at/verify-vcluster --namespace workspace || true
  kube get datalabs.versioneer.at/s-john datalabs.versioneer.at/s-jane --namespace workspace || true
  kube get objects.kubernetes.m.crossplane.io --namespace workspace --selector crossplane.io/composite=verify-vcluster || true
  kube get statefulsets,pods,httproutes,backendtlspolicies --namespace "${VCLUSTER_NAMESPACE}" || true
  kube get pvc,cronjobs,jobs,volumesnapshots --namespace "${VCLUSTER_NAMESPACE}" || true
  kube get events --namespace "${VCLUSTER_NAMESPACE}" --sort-by=.lastTimestamp | tail -25 || true
  kube logs statefulset/vcluster-vc0 --namespace "${VCLUSTER_NAMESPACE}" --tail=40 || true
  printf 'vCluster resources were kept for diagnosis.\n' >&2
  exit "${result}"
}
trap report_failure ERR

build_catalog_image() {
  local digest
  digest="$(cat "${REPO_ROOT}/tests/vcluster/"{catalog.Dockerfile,initialize.py,requirements.txt,tooling/requirements.txt} | sha256sum | cut -c1-16)"
  catalog_image="${VCLUSTER_CATALOG_IMAGE:-}"
  mkdir -p "${work_directory}/docker" "${work_directory}/build/tests/vcluster"
  cp "${REPO_ROOT}/tests/vcluster/"{initialize.py,requirements.txt} "${work_directory}/build/tests/vcluster/"
  mkdir -p "${work_directory}/build/tests/vcluster/tooling"
  cp "${REPO_ROOT}/tests/vcluster/tooling/requirements.txt" "${work_directory}/build/tests/vcluster/tooling/"
  if [[ -z "${catalog_image}" ]]; then
    require_command docker
    catalog_image="$(test_image_name "datalab-stac:${digest}")"
    if ! DOCKER_CONFIG="${work_directory}/docker" docker image inspect "${catalog_image}" >/dev/null 2>&1; then
      DOCKER_CONFIG="${work_directory}/docker" docker build --provenance=false --tag "${catalog_image}" \
        --file "${REPO_ROOT}/tests/vcluster/catalog.Dockerfile" "${work_directory}/build"
    fi
    publish_test_image "${catalog_image}" "${work_directory}/docker"
  fi
  python3 - "${REPO_ROOT}/examples/vcluster/stac-fastapi.yaml" "${catalog_image}" "${PROVIDER_DATALAB_IMAGE_PULL_SECRET:-}" >"${work_directory}/catalog.json" <<'CATALOG'
import json, sys, yaml
from pathlib import Path
documents = list(yaml.safe_load_all(Path(sys.argv[1]).read_text().replace('__CATALOG_IMAGE__', sys.argv[2])))
if sys.argv[3]:
    for document in documents:
        template = document.get('spec', {}).get('template')
        if template:
            template['spec']['imagePullSecrets'] = [{'name': sys.argv[3]}]
print(json.dumps(documents))
CATALOG
}

build_client_image() {
  local digest
  if [[ -n "${VCLUSTER_CLIENT_IMAGE:-}" ]]; then
    client_image="${VCLUSTER_CLIENT_IMAGE}"
    return
  fi
  require_command docker
  digest="$(sha256sum "${REPO_ROOT}/tests/vcluster/client.Dockerfile" | cut -c1-16)"
  client_image="$(test_image_name "datalab-vcluster-client:${digest}")"
  mkdir -p "${work_directory}/client-build" "${work_directory}/docker"
  if ! DOCKER_CONFIG="${work_directory}/docker" docker image inspect "${client_image}" >/dev/null 2>&1; then
    DOCKER_CONFIG="${work_directory}/docker" docker build --provenance=false --tag "${client_image}" \
      --file "${REPO_ROOT}/tests/vcluster/client.Dockerfile" "${work_directory}/client-build"
  fi
  publish_test_image "${client_image}" "${work_directory}/docker"
}

install_client_kubectl() {
  # Large API copies can time out through nested forwards. Send the small installer.
  kube cp "${REPO_ROOT}/scripts/install-tools.py" workspace/verify-vcluster-client:/tmp/install-tools.py
  kube cp "${REPO_ROOT}/scripts/tools.json" workspace/verify-vcluster-client:/tmp/tools.json
  kube --request-timeout=5m exec verify-vcluster-client --namespace workspace -- \
    python3 /tmp/install-tools.py kubectl --directory /tmp
}

install_prerequisites() {
  create_ingress_certificate
  install_cnpg
  mkdir -p "${PROVIDER_DATALAB_HELM_HOME}"
  python3 "${REPO_ROOT}/scripts/components.py" contour-provisioner --manifest | \
    kube apply --server-side -f -
  wait_for_crd_established httproutes.gateway.networking.k8s.io
  wait_for_crd_established backendtlspolicies.gateway.networking.k8s.io
  kube rollout status deployment/contour-gateway-provisioner --namespace projectcontour --timeout=10m
  # Fresh certificates must remain valid through the full profile.
  openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj '/CN=*.lab.acme.com' \
    -addext 'subjectAltName=DNS:*.lab.acme.com' \
    -keyout "${work_directory}/gateway.key" -out "${work_directory}/gateway.crt" >/dev/null 2>&1
  kube create secret tls verify-vcluster-gateway-tls --namespace projectcontour \
    --cert "${work_directory}/gateway.crt" --key "${work_directory}/gateway.key" \
    --dry-run=client -o yaml | kube apply -f -
  kube apply -f "${MANIFEST_DIR}/vcluster/gateway.yaml"
  if ! kube get deployment/keycloak --namespace keycloak >/dev/null 2>&1; then
    kube apply -f "${MANIFEST_DIR}/s3/keycloak.yaml"
  fi
  # Reuse a certificate with two hours left so retries keep the identity service ready.
  if ! kube get secret/verify-vcluster-issuer --namespace keycloak \
      -o jsonpath='{.data.tls\.crt}' 2>/dev/null | base64 --decode >"${work_directory}/issuer.crt" || \
     ! openssl x509 -in "${work_directory}/issuer.crt" -noout -checkend 7200 >/dev/null 2>&1 || \
     ! openssl verify -CAfile "${work_directory}/issuer.crt" -verify_hostname keycloak.keycloak \
       "${work_directory}/issuer.crt" >/dev/null 2>&1; then
    openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj '/CN=keycloak.keycloak' \
      -addext 'subjectAltName=DNS:keycloak.keycloak' \
      -keyout "${work_directory}/issuer.key" -out "${work_directory}/issuer.crt" >/dev/null 2>&1
    kube create secret tls verify-vcluster-issuer --namespace keycloak \
      --cert "${work_directory}/issuer.crt" --key "${work_directory}/issuer.key" \
      --dry-run=client -o yaml | kube apply -f -
  fi
  # TLS bootstrap needs a configuration build and database schema setup.
  kube patch deployment/keycloak --namespace keycloak --type=strategic --patch "$(
    jq -n --arg checksum "$(sha256sum "${work_directory}/issuer.crt" | cut -d' ' -f1)" '{spec:{progressDeadlineSeconds:900,template:{
      metadata:{annotations:{"datalabs.versioneer.at/issuer-checksum":$checksum}},
      spec:{containers:[{name:"keycloak",args:["start-dev","--import-realm","--https-certificate-file=/tls/tls.crt","--https-certificate-key-file=/tls/tls.key"],
        startupProbe:{periodSeconds:5,failureThreshold:120},
        volumeMounts:[{name:"tls",mountPath:"/tls",readOnly:true}]}],
        volumes:[{name:"tls",secret:{secretName:"verify-vcluster-issuer"}}]}}}}'
  )"
  kube patch service/keycloak --namespace keycloak --type=strategic \
    --patch '{"spec":{"ports":[{"name":"https","port":8443,"targetPort":8443}]}}'
  kube rollout status deployment/keycloak --namespace keycloak --timeout=15m
  kube wait gateway/verify-vcluster --namespace projectcontour --for=condition=Programmed --timeout=10m
  kube wait deployment --namespace projectcontour --selector gateway.networking.k8s.io/gateway-name=verify-vcluster \
    --for=condition=Available --timeout=10m
  apply_environment_config "${MANIFEST_DIR}/vcluster/environmentconfig.yaml"
  kube patch environmentconfig/datalab-vcluster-it --type=merge \
    --patch "$(jq -n --rawfile ca "${work_directory}/issuer.crt" --rawfile gateway_ca "${work_directory}/gateway.crt" \
      --arg snapshot_class "${PROVIDER_DATALAB_SNAPSHOT_CLASS:-}" \
      '{data:{vcluster:{issuerCA:$ca},ingress:{certificateAuthority:$gateway_ca},volumes:{snapshotClassName:$snapshot_class,schedule:"0 0 1 1 *"}}}')"
}


verify_volume_bindings() {
  local gateway_ip=$1 deadline operation control_plane_uid
  local -a binding_objects
  control_plane_uid="$(kube get statefulset/vcluster-vc0 --namespace "${VCLUSTER_NAMESPACE}" -o jsonpath='{.metadata.uid}')"
  mapfile -t binding_objects < <(kube get objects.kubernetes.m.crossplane.io --namespace workspace \
    --selector crossplane.io/composite=verify-vcluster,datalabs.versioneer.at/vcluster=vc0 -o json | jq -r '
      [.items[] | .spec.forProvider.manifest as $manifest |
      if $manifest.kind == "PersistentVolumeClaim" and $manifest.metadata.namespace == "demo" and $manifest.metadata.name == "demo" then
        .metadata.name, (.spec.references[] | .dependsOn.name | select(startswith("vcluster-")))
      elif $manifest.kind == "PersistentVolume" and $manifest.metadata.labels["datalabs.versioneer.at/volume"] == "demo" then
        .metadata.name
      else empty end] | unique[]')
  bound_volume_uid="$(kube get pvc/volume-demo --namespace "${VCLUSTER_NAMESPACE}" -o jsonpath='{.metadata.uid}')"
  bound_backup_uid="$(kube get cronjob/volume-snapshot-demo --namespace "${VCLUSTER_NAMESPACE}" -o jsonpath='{.metadata.uid}')"
  for operation in patch delete; do
    local -a request=("${operation}" pvc/volume-demo --namespace "${VCLUSTER_NAMESPACE}"
      --as "system:serviceaccount:${VCLUSTER_NAMESPACE}:vc-vcluster-vc0" --dry-run=server)
    if [[ "${operation}" == patch ]]; then
      request+=(--type=merge --patch '{"metadata":{"labels":{"test-change":"denied"}}}')
    fi
    if kube "${request[@]}" >"${work_directory}/volume-admission.log" 2>&1; then
      printf 'The syncer could %s a host-owned volume.\n' "${operation}" >&2
      return 1
    fi
    grep -F 'Datalab owns this host PVC' "${work_directory}/volume-admission.log" >/dev/null
  done
  kube exec verify-vcluster-client --namespace workspace -- python3 -u /test/e2e.py "${gateway_ip}" --volume-binding write
  check_volume_backup_access "${VCLUSTER_NAMESPACE}" volume-demo volume-snapshot-demo
  kube create job test-bound-volume-backup --from=cronjob/volume-snapshot-demo --namespace "${VCLUSTER_NAMESPACE}"
  deadline=$((SECONDS + 900))
  while true; do
    local job_status
    job_status="$(kube get job/test-bound-volume-backup --namespace "${VCLUSTER_NAMESPACE}" -o json)"
    if jq -e 'any(.status.conditions[]?; .type == "Complete" and .status == "True")' <<<"${job_status}" >/dev/null; then
      break
    fi
    if ((SECONDS >= deadline)) || jq -e 'any(.status.conditions[]?; .type == "Failed" and .status == "True")' <<<"${job_status}" >/dev/null; then
      kube describe job/test-bound-volume-backup --namespace "${VCLUSTER_NAMESPACE}" || true
      kube logs job/test-bound-volume-backup --namespace "${VCLUSTER_NAMESPACE}" --tail=80 || true
      return 1
    fi
    sleep 3
  done
  bound_snapshot="$(kube get volumesnapshots --namespace "${VCLUSTER_NAMESPACE}" \
    --selector "datalabs.versioneer.at/volume=demo,datalabs.versioneer.at/source-pvc-uid=${bound_volume_uid}" -o json \
    | jq -er '[.items[] | select(.status.readyToUse == true)] | if length == 1 then .[0].metadata.name else error("Expected one ready volume snapshot") end')"
  bound_snapshot_uid="$(kube get "volumesnapshot/${bound_snapshot}" --namespace "${VCLUSTER_NAMESPACE}" -o jsonpath='{.metadata.uid}')"
  kube exec verify-vcluster-client --namespace workspace -- python3 -u /test/e2e.py "${gateway_ip}" --volume-binding recreate-claim
  kube patch datalab/verify-vcluster --namespace workspace --type=merge --patch '{"spec":{"vclusters":{"vc0":{"volumeBindings":[]}}}}'
  kube exec verify-vcluster-client --namespace workspace -- python3 -u /test/e2e.py "${gateway_ip}" --volume-binding absent
  # Wait for old binding policies before using the same target again.
  for object in "${binding_objects[@]}"; do
    kube wait "object.kubernetes.m.crossplane.io/${object}" --namespace workspace --for=delete --timeout=5m
  done
  [[ "$(kube get statefulset/vcluster-vc0 --namespace "${VCLUSTER_NAMESPACE}" -o jsonpath='{.metadata.uid}')" == "${control_plane_uid}" ]]
  printf 'PASS binding policies are deleted while the control plane remains\n'
  kube patch datalab/verify-vcluster --namespace workspace --type=merge \
    --patch '{"spec":{"vclusters":{"vc0":{"volumeBindings":[{"name":"demo","target":{"namespace":"demo","name":"demo"}}]}}}}'
  deadline=$((SECONDS + 900))
  until kube get datalab/verify-vcluster --namespace workspace -o json | jq -e '
    .metadata.generation as $generation |
    any(.status.conditions[]?; .type == "Ready" and .status == "True" and .observedGeneration == $generation)
  ' >/dev/null; do
    ((SECONDS < deadline)) || return 1
    sleep 3
  done
  kube exec verify-vcluster-client --namespace workspace -- python3 -u /test/e2e.py "${gateway_ip}" --volume-binding check
  deadline=$((SECONDS + 90))
  until kube get pods --namespace "${VCLUSTER_NAMESPACE}" -o json | jq -e '
    [.items[] | select(.metadata.annotations["vcluster.loft.sh/object-name"] == "test-bound-volume"
       and .metadata.annotations["vcluster.loft.sh/object-namespace"] == "demo")] |
    length == 1 and
    (.[0].spec.volumes | any(.name == "data" and .persistentVolumeClaim.claimName == "volume-demo" and .persistentVolumeClaim.readOnly == true)) and
    (.[0].spec.volumes | any(.name == "scratch" and has("emptyDir")))
  ' >/dev/null; do
    ((SECONDS < deadline)) || return 1
    sleep 3
  done
  verify_bound_volume_preserved
  printf 'PASS host admission preserves read-only mounts and other volumes; virtual claim and binding recreation keep data\n'
}

verify_bound_volume_preserved() {
  [[ "$(kube get pvc/volume-demo --namespace "${VCLUSTER_NAMESPACE}" -o jsonpath='{.metadata.uid}')" == "${bound_volume_uid}" ]]
  [[ "$(kube get cronjob/volume-snapshot-demo --namespace "${VCLUSTER_NAMESPACE}" -o jsonpath='{.metadata.uid}')" == "${bound_backup_uid}" ]]
  kube get "volumesnapshot/${bound_snapshot}" --namespace "${VCLUSTER_NAMESPACE}" -o json \
    | jq -e --arg uid "${bound_snapshot_uid}" '.metadata.uid == $uid and .status.readyToUse == true' >/dev/null
}


verify_custom_connections() {
  local team namespace key deadline expected
  kube patch environmentconfig/datalab-custom --type=merge --patch \
    '{"data":{"customSecrets":[{"name":"apikey-1"},{"name":"apikey-2"}],"packageR":{"enabled":false},"registry":{"enabled":false}}}'
  for team in s-john s-jane; do
    kube create secret generic "${team}" --namespace workspace \
      --from-literal=AWS_ACCESS_KEY_ID=minioadmin --from-literal=AWS_SECRET_ACCESS_KEY=minioadmin \
      --dry-run=client -o yaml | kube apply -f -
    kube apply -f - <<DATALAB
apiVersion: versioneer.at/v1
kind: Datalab
metadata:
  name: ${team}
  namespace: workspace
spec:
  crossplane:
    compositionRef: {name: test-datalab}
  environmentName: datalab-custom
  users: [verify-s3]
DATALAB
  done
  for team in s-john s-jane; do
    namespace="$(wait_for_runtime_namespace "${team}")"
    [[ "${namespace}" == "${team}" ]]
    kube wait "datalabs.versioneer.at/${team}" --namespace workspace --for=condition=Ready --timeout=10m
    kube get "datalabs.versioneer.at/${team}" --namespace workspace -o json \
      | jq -e '[.status.connections[]? | select(.type == "custom")] | length == 0' >/dev/null
    for key in apikey-1 apikey-2; do
      [[ "${team}" != s-jane || "${key}" != apikey-2 ]] || continue
      kube create secret generic "${key}" --namespace "${namespace}" \
        --from-literal=token=integration-test --dry-run=client -o yaml | kube apply -f -
    done
  done
  for team in s-john s-jane; do
    expected='["apikey-1","apikey-2"]'
    [[ "${team}" != s-jane ]] || expected='["apikey-1"]'
    deadline=$((SECONDS + 600))
    until kube get "datalabs.versioneer.at/${team}" --namespace workspace -o json | jq -e --argjson expected "${expected}" \
      '([.status.connections[]? | select(.type == "custom") | .name] | sort) == $expected and all(.status.connections[]?; .ready)' >/dev/null; do
      ((SECONDS < deadline)) || return 1
      sleep 2
    done
    kube wait "datalabs.versioneer.at/${team}" --namespace workspace --for=condition=Ready --timeout=5m
    python3 "${INTEGRATION_DIR}/verify-service-connections.py" \
      --kubeconfig "${PROVIDER_DATALAB_KUBECONFIG}" --context "${KUBECTL_CONTEXT}" --namespace workspace --datalab "${team}"
  done
  printf 'PASS custom connections include available Secrets and omit missing sources\n'
  if [[ "${KEEP_VCLUSTER_RESOURCES}" != 1 ]]; then
    kube delete datalabs.versioneer.at/s-john datalabs.versioneer.at/s-jane --namespace workspace --wait=false
    for team in s-john s-jane; do
      kube wait "datalabs.versioneer.at/${team}" --namespace workspace --for=delete --timeout=10m
      python3 "${INTEGRATION_DIR}/verify-service-connections.py" \
        --kubeconfig "${PROVIDER_DATALAB_KUBECONFIG}" --context "${KUBECTL_CONTEXT}" --namespace workspace --datalab "${team}" --deleted
      kube wait "namespace/${team}" --for=delete --timeout=10m
    done
    kube delete secret/s-john secret/s-jane --namespace workspace
  fi
}

verify_hibernation() {
  local previous_pvcs services deadline
  previous_pvcs="$(kube get pvc --namespace "${VCLUSTER_NAMESPACE}" -o json | jq -c '[.items[] | [.metadata.name,.metadata.uid]] | sort')"
  services="$(kube get service/vcluster-vc0 service/vcluster-vc1 --namespace "${VCLUSTER_NAMESPACE}" -o json | jq -c '[.items[].metadata.uid]')"
  kube patch datalabs.versioneer.at/verify-vcluster --namespace workspace --type=merge \
    --patch '{"spec":{"vclusters":{"vc0":{"hibernated":true},"vc1":{"hibernated":true}}}}'
  deadline=$((SECONDS + 900))
  until kube get datalabs.versioneer.at/verify-vcluster --namespace workspace -o json | jq -e '
    .metadata.generation as $generation |
    (.status.vclusters | length == 2) and
    all(.status.vclusters[]; .phase == "Hibernated" and .observedGeneration == $generation)
  ' >/dev/null; do
    ((SECONDS < deadline)) || return 1
    sleep 3
  done
  kube get statefulset/vcluster-vc0 statefulset/vcluster-vc1 --namespace "${VCLUSTER_NAMESPACE}" -o json \
    | jq -e 'all(.items[]; .spec.replicas == 0 and (.status.replicas // 0) == 0)' >/dev/null
  kube get pods --namespace "${VCLUSTER_NAMESPACE}" -o json | jq -e --argjson services "${services}" '
    all(.items[]; all(.metadata.ownerReferences[]?;
      .kind != "Service" or (.uid as $uid | $services | index($uid) == null)))
  ' >/dev/null
  kube get datalabs.versioneer.at/verify-vcluster --namespace workspace -o json | jq -e '
    all(.status.connections[] | select(.type == "vcluster"); .ready == false)
  ' >/dev/null
  kube get cluster.postgresql.cnpg.io/postgres-pg0 --namespace "${VCLUSTER_NAMESPACE}" -o json \
    | jq -e 'any(.status.conditions[]?; .type == "Ready" and .status == "True")' >/dev/null
  [[ "$(kube get pvc --namespace "${VCLUSTER_NAMESPACE}" -o json | jq -c '[.items[] | [.metadata.name,.metadata.uid]] | sort')" == "${previous_pvcs}" ]]
  kube wait datalabs.versioneer.at/verify-vcluster --namespace workspace --for=condition=Ready --timeout=5m
  printf 'PASS both instances hibernate without synced Pods and retain their PVCs and PostgreSQL\n'

  kube patch datalabs.versioneer.at/verify-vcluster --namespace workspace --type=merge \
    --patch '{"spec":{"vclusters":{"vc0":{"hibernated":false},"vc1":{"hibernated":false}}}}'
  deadline=$((SECONDS + 900))
  until kube get datalabs.versioneer.at/verify-vcluster --namespace workspace -o json | jq -e '
    .metadata.generation as $generation |
    (.status.vclusters | length == 2) and
    all(.status.vclusters[]; .phase == "Running" and .observedGeneration == $generation)
  ' >/dev/null; do
    ((SECONDS < deadline)) || return 1
    sleep 3
  done
  kube wait datalabs.versioneer.at/verify-vcluster --namespace workspace --for=condition=Ready --timeout=15m
  [[ "$(kube get pvc --namespace "${VCLUSTER_NAMESPACE}" -o json | jq -c '[.items[] | [.metadata.name,.metadata.uid]] | sort')" == "${previous_pvcs}" ]]
  printf 'PASS both instances resume with the same PVC identities\n'
}

verify_vcluster() {
  local service gateway_ip deadline administrator_secret editor_secret other_secret previous_configuration configuration_path
  if [[ -n "${PROVIDER_DATALAB_IMAGE_PULL_SECRET:-}" ]]; then
    kube patch environmentconfig/datalab-vcluster-it --type=merge --patch "$(
      jq -cn --arg name "${PROVIDER_DATALAB_IMAGE_PULL_SECRET}" \
        '{data:{customSecrets:[{name:$name,namespace:"workspace"}]}}'
    )"
  fi
  python3 - "${MANIFEST_DIR}/vcluster/datalab.yaml" "${PROVIDER_DATALAB_IMAGE_PULL_SECRET:-}" "${snapshots_enabled}" <<'DATALAB' | kube apply -f -
from pathlib import Path
import sys
import yaml

document = yaml.safe_load(Path(sys.argv[1]).read_text())
if sys.argv[3] != '1':
    document['spec'].pop('volumes')
    document['spec']['vclusters']['vc0'].pop('volumeBindings')
if sys.argv[2]:
    document['spec']['vclusters']['vc0']['secretBindings'].append({
        'type': 'custom', 'name': sys.argv[2],
        'target': {'namespace': 'demo', 'name': sys.argv[2]},
    })
yaml.safe_dump(document, sys.stdout)
DATALAB
  runtime_namespace="$(wait_for_runtime_namespace verify-vcluster)"
  [[ "${runtime_namespace}" == "${VCLUSTER_NAMESPACE}" ]]
  kube apply -f "${MANIFEST_DIR}/vcluster/postgres-network.yaml"
  for instance in vc0 vc1; do
    kube wait "statefulset/vcluster-${instance}" --namespace "${runtime_namespace}" --for=create --timeout=10m
    kube rollout status "statefulset/vcluster-${instance}" --namespace "${runtime_namespace}" --timeout=15m
  done
  kube wait cluster.postgresql.cnpg.io/postgres-pg0 --namespace "${runtime_namespace}" --for=create --timeout=10m
  deadline=$((SECONDS + 900))
  until kube get cluster.postgresql.cnpg.io/postgres-pg0 --namespace "${runtime_namespace}" -o json | jq -e 'any(.status.conditions[]?; .type == "Ready" and .status == "True")' >/dev/null; do
    ((SECONDS < deadline)) || return 1
    sleep 5
  done
  wait_for_connection_secret verify-vcluster-postgres-pg0 verify-vcluster 600 password host
  verify_workload_probes "${runtime_namespace}"
  connection_secret() {
    kube get datalabs.versioneer.at/verify-vcluster --namespace workspace -o json | jq -er --arg instance "$1" --arg group "$2" \
      '.status.connections[] | select(.type == "vcluster" and .instance == $instance and .group == $group) | .secretRef.name'
  }
  administrator_secret="$(connection_secret vc0 cluster-admin)"
  editor_secret="$(connection_secret vc0 namespace-demo)"
  other_secret="$(connection_secret vc1 cluster-admin)"
  for profile in "${administrator_secret}" "${editor_secret}" "${other_secret}"; do
    wait_for_connection_secret "${profile}" verify-vcluster 600 kubeconfig
    kube get "secret/${profile}" --namespace workspace -o json \
      | jq -e '(.data | keys | sort) == ["client-id", "issuer-url", "kubeconfig"]' >/dev/null
  done
  kube wait datalabs.versioneer.at/verify-vcluster --namespace workspace --for=condition=Ready --timeout=15m
  kube get datalabs.versioneer.at/verify-vcluster --namespace workspace -o json | python3 -c '
import json, sys
status = json.load(sys.stdin)["status"]
assert status["oauth2"] == [{"name": "verify-vcluster", "type": "client", "issuerUrl": "https://keycloak.keycloak:8443/realms/integration", "secretRef": {"name": "verify-vcluster-oauth-client", "namespace": "workspace"}, "ready": True}]
assert not any(c["type"] == "oauth2" for c in status["connections"])
connections = [c for c in status["connections"] if c["type"] == "vcluster"]
assert len(connections) == 4 and all(c["ready"] for c in connections)
assert {c["instance"] for c in connections} == {"vc0", "vc1"}
assert all(set(c) <= {"name", "type", "instance", "group", "targetNamespace", "role", "endpoint", "ready", "secretRef"} for c in connections)
print("PASS connection status contains ready profile references without credentials")'
  if kube patch datalabs.versioneer.at/verify-vcluster --namespace workspace --subresource=status --dry-run=server --type=merge \
    --patch '{"status":{"oauth2":[{"name":"duplicate","type":"client","issuerUrl":"https://identity.example","secretRef":{"name":"test","namespace":"workspace"},"ready":false},{"name":"duplicate","type":"client","issuerUrl":"https://identity.example","secretRef":{"name":"test","namespace":"workspace"},"ready":false}]}}' \
    >"${work_directory}/oauth-admission.log" 2>&1; then
    printf 'Kubernetes admitted duplicate OAuth2 discovery names.\n' >&2
    return 1
  fi
  grep -F 'Duplicate value' "${work_directory}/oauth-admission.log" >/dev/null
  printf 'PASS OAuth2 discovery is separate and Kubernetes rejects duplicate client names\n'
  python3 "${INTEGRATION_DIR}/verify-oauth-discovery.py" \
    --kubeconfig "${PROVIDER_DATALAB_KUBECONFIG}" --context "${KUBECTL_CONTEXT}" --datalab verify-vcluster
  for instance in vc0 vc1; do
    if kube create --dry-run=server --as "system:serviceaccount:${runtime_namespace}:vc-vcluster-${instance}" \
      -f - >"${work_directory}/storage-admission.log" 2>&1 <<PVC
apiVersion: v1
kind: PersistentVolumeClaim
metadata: {name: unapproved-storage-probe, namespace: ${runtime_namespace}}
spec:
  accessModes: [ReadWriteOnce]
  storageClassName: unapproved-storage
  resources: {requests: {storage: 1Mi}}
PVC
    then
      printf 'The host admitted a disallowed StorageClass for %s.\n' "${instance}" >&2
      return 1
    fi
    grep -F 'must use an allowed' "${work_directory}/storage-admission.log" >/dev/null
  done
  printf 'PASS host storage admission applies to both syncer identities\n'
  resource_budget
  service="$(kube get services --namespace projectcontour --selector gateway.networking.k8s.io/gateway-name=verify-vcluster -o json | jq -er '[.items[] | select(any(.spec.ports[]; .port == 443)) | .metadata.name] | if length == 1 then .[0] else error("Expected one HTTPS Gateway Service") end')"
  gateway_ip="$(kube get "service/${service}" --namespace projectcontour -o jsonpath='{.spec.clusterIP}')"
  kube create configmap verify-vcluster-client --namespace workspace \
    --from-file="${work_directory}/gateway.crt" --from-file="${work_directory}/issuer.crt" \
    --from-file="${work_directory}/catalog.json" --from-file="${REPO_ROOT}/tests/vcluster/e2e.py" \
    --from-file="${REPO_ROOT}/tests/vcluster/volume_bindings.py" \
    --dry-run=client -o yaml | kube apply -f -
  kube delete pod/verify-vcluster-client --namespace workspace --ignore-not-found --wait=true
  apply_template "${MANIFEST_DIR}/vcluster/client.yaml" \
    ADMINISTRATOR_SECRET "${administrator_secret}" EDITOR_SECRET "${editor_secret}" OTHER_SECRET "${other_secret}" \
    CLIENT_IMAGE "${client_image}" IMAGE_PULL_SECRETS "$(test_image_pull_secrets)"
  kube wait pod/verify-vcluster-client --namespace workspace --for=condition=Ready --timeout=5m
  install_client_kubectl
  kube exec verify-vcluster-client --namespace workspace -- python3 -u /test/e2e.py "${gateway_ip}" --storage-class "${PROVIDER_DATALAB_STORAGE_CLASS}" --member-roles
  kube exec verify-vcluster-client --namespace workspace -- python3 -u /test/e2e.py "${gateway_ip}" --recreate-client
  kube patch datalabs.versioneer.at/verify-vcluster --namespace workspace --type=merge --patch '{"spec":{"users":[]}}'
  kube exec verify-vcluster-client --namespace workspace -- python3 -u /test/e2e.py "${gateway_ip}" --storage-class "${PROVIDER_DATALAB_STORAGE_CLASS}" --member-removed
  kube patch datalabs.versioneer.at/verify-vcluster --namespace workspace --type=merge --patch '{"spec":{"users":["verify-s3","verify-vcluster-member"]}}'
  kube exec verify-vcluster-client --namespace workspace -- python3 -u /test/e2e.py "${gateway_ip}" --storage-class "${PROVIDER_DATALAB_STORAGE_CLASS}" --member-roles
  kube exec verify-vcluster-client --namespace workspace -- python3 -u /test/e2e.py "${gateway_ip}" --storage-class "${PROVIDER_DATALAB_STORAGE_CLASS}"
  if ((snapshots_enabled)); then verify_volume_bindings "${gateway_ip}"; fi
  verify_hibernation
  kube exec verify-vcluster-client --namespace workspace -- python3 -u /test/e2e.py "${gateway_ip}" --storage-class "${PROVIDER_DATALAB_STORAGE_CLASS}" --check-only
  kube rollout restart statefulset/vcluster-vc0 --namespace "${runtime_namespace}"
  kube rollout status statefulset/vcluster-vc0 --namespace "${runtime_namespace}" --timeout=10m
  kube exec verify-vcluster-client --namespace workspace -- python3 -u /test/e2e.py "${gateway_ip}" --storage-class "${PROVIDER_DATALAB_STORAGE_CLASS}" --check-only
  kube patch datalabs.versioneer.at/verify-vcluster --namespace workspace --type=json \
    --patch '[{"op":"replace","path":"/spec/vclusters/vc0/groups/0/role","value":"view"}]'
  kube exec verify-vcluster-client --namespace workspace -- python3 -u /test/e2e.py "${gateway_ip}" --storage-class "${PROVIDER_DATALAB_STORAGE_CLASS}" --read-only
  configuration_path='{.spec.template.metadata.annotations.datalabs\.versioneer\.at/configuration-checksum}'
  previous_configuration="$(kube get statefulset/vcluster-vc0 --namespace "${runtime_namespace}" -o "jsonpath=${configuration_path}")"
  kube patch datalabs.versioneer.at/verify-vcluster --namespace workspace --type=json \
    --patch '[{"op":"remove","path":"/spec/vclusters/vc0/groups/0"}]'
  kube exec verify-vcluster-client --namespace workspace -- python3 -u /test/e2e.py "${gateway_ip}" --storage-class "${PROVIDER_DATALAB_STORAGE_CLASS}" --revoked
  kube wait "secret/${editor_secret}" --namespace workspace --for=delete --timeout=5m
  # Role removal can revoke access before the changed authentication configuration rolls out.
  deadline=$((SECONDS + 600))
  until [[ "$(kube get statefulset/vcluster-vc0 --namespace "${runtime_namespace}" -o "jsonpath=${configuration_path}")" != "${previous_configuration}" ]]; do
    ((SECONDS < deadline)) || { printf 'The virtual cluster authentication configuration did not change.\n' >&2; return 1; }
    sleep 3
  done
  kube rollout status statefulset/vcluster-vc0 --namespace "${runtime_namespace}" --timeout=10m
  if ((snapshots_enabled)); then
    kube exec verify-vcluster-client --namespace workspace -- python3 -u /test/e2e.py "${gateway_ip}" --volume-binding check
  fi
  python3 "${INTEGRATION_DIR}/wait-for-cleanup.py" --kubeconfig "${PROVIDER_DATALAB_KUBECONFIG}" \
    --context "${KUBECTL_CONTEXT}" --datalab verify-vcluster --instance vc0 --capture "${work_directory}/vc0-records.json"
  kube patch datalabs.versioneer.at/verify-vcluster --namespace workspace --type=json --patch '[{"op":"remove","path":"/spec/vclusters/vc0"}]'
  python3 "${INTEGRATION_DIR}/wait-for-cleanup.py" --kubeconfig "${PROVIDER_DATALAB_KUBECONFIG}" \
    --context "${KUBECTL_CONTEXT}" --datalab verify-vcluster --records "${work_directory}/vc0-records.json"
  kube wait statefulset/vcluster-vc0 --namespace "${runtime_namespace}" --for=delete --timeout=10m
  kube exec verify-vcluster-client --namespace workspace -- python3 -u /test/e2e.py "${gateway_ip}" --storage-class "${PROVIDER_DATALAB_STORAGE_CLASS}" --other-only
  kube exec verify-vcluster-client --namespace workspace -- python3 -u /test/e2e.py "${gateway_ip}" --storage-class "${PROVIDER_DATALAB_STORAGE_CLASS}" --member-roles --member-instance vc1
  kube get cluster.postgresql.cnpg.io/postgres-pg0 --namespace "${runtime_namespace}" -o json | jq -e 'any(.status.conditions[]?; .type == "Ready" and .status == "True")' >/dev/null
  if ((snapshots_enabled)); then
    verify_bound_volume_preserved
    printf 'PASS a running bound workload does not block vc0 removal; host volume, backup schedule, and snapshot remain\n'
  fi
  printf 'PASS PostgreSQL remains ready after removing vc0\n'
}

verify_name_admission() {
  python3 - "${MANIFEST_DIR}/vcluster/datalab.yaml" "${PROVIDER_DATALAB_KUBECONFIG}" "${KUBECTL_CONTEXT}" <<'ADMISSION'
from copy import deepcopy
from pathlib import Path
import subprocess, sys, yaml
source = yaml.safe_load(Path(sys.argv[1]).read_text())
for config in ({}, {"groups": []}, {"groups": [{"name": "cluster-admin", "namespace": "*", "role": "cluster-admin"}]}):
    value = deepcopy(source)
    value["spec"]["vclusters"] = {"vc0": config}
    result = subprocess.run(['kubectl', '--kubeconfig', sys.argv[2], '--context', sys.argv[3], 'apply', '--dry-run=server', '-f', '-'], input=yaml.safe_dump(value), text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
value = deepcopy(source)
value["spec"]["vclusters"] = {"vc0": {"groups": [{"name": "cluster-admin", "namespace": "demo", "role": "view"}]}}
result = subprocess.run(['kubectl', '--kubeconfig', sys.argv[2], '--context', sys.argv[3], 'apply', '--dry-run=server', '-f', '-'], input=yaml.safe_dump(value), text=True, capture_output=True)
assert result.returncode != 0 and 'built-in cluster-admin profile cannot be changed' in result.stderr, result.stderr
print('PASS Kubernetes admission accepts implicit admin profiles and rejects a reserved-name override')
for field in ('vclusters', 'stores'):
    for key in ('0bad', 'Bad', 'bad_name', 'bad-', 'a' * 64):
        value = deepcopy(source)
        config = next(iter(value['spec'][field].values())) if field in value['spec'] else {'type': 'valkey', 'storage': '1Gi'}
        value['spec'][field] = {key: config}
        result = subprocess.run(['kubectl', '--kubeconfig', sys.argv[2], '--context', sys.argv[3], 'apply', '--dry-run=server', '-f', '-'], input=yaml.safe_dump(value), text=True, capture_output=True)
        assert result.returncode != 0 and 'Instance names must' in result.stderr, result.stderr
print('PASS Kubernetes admission rejects invalid instance names for all maps')
ADMISSION
}

main() {
  require_cluster
  check_volume_binding_settings
  if snapshot_tests_available verify-vcluster; then snapshots_enabled=1; fi
  install_prerequisites
  build_catalog_image
  build_client_image
  verify_name_admission
  verify_custom_connections
  verify_vcluster
  if [[ "${KEEP_VCLUSTER_RESOURCES}" != 1 ]]; then
    kube delete pod/verify-vcluster-client configmap/verify-vcluster-client --namespace workspace --ignore-not-found
    # Delete the remaining instance while its API is stopped.
    kube patch datalabs.versioneer.at/verify-vcluster --namespace workspace --type=merge \
      --patch '{"spec":{"vclusters":{"vc1":{"hibernated":true}}}}'
    deadline=$((SECONDS + 900))
    until kube get datalabs.versioneer.at/verify-vcluster --namespace workspace -o json | \
      jq -e 'any(.status.vclusters[]?; .name == "vc1" and .phase == "Hibernated")' >/dev/null; do
      ((SECONDS < deadline)) || return 1
      sleep 3
    done
    python3 "${INTEGRATION_DIR}/wait-for-cleanup.py" --kubeconfig "${PROVIDER_DATALAB_KUBECONFIG}" \
      --context "${KUBECTL_CONTEXT}" --datalab verify-vcluster --capture "${work_directory}/lab-records.json"
    kube delete datalabs.versioneer.at/verify-vcluster --namespace workspace --wait=false
    kube wait datalabs.versioneer.at/verify-vcluster --namespace workspace --for=delete --timeout=10m
    # Namespace cleanup can retry after half of PostgreSQL's 1800-second shutdown grace.
    kube wait "namespace/${VCLUSTER_NAMESPACE}" --for=delete --timeout=20m
    python3 "${INTEGRATION_DIR}/wait-for-cleanup.py" --kubeconfig "${PROVIDER_DATALAB_KUBECONFIG}" \
      --context "${KUBECTL_CONTEXT}" --datalab verify-vcluster --records "${work_directory}/lab-records.json"
    python3 "${INTEGRATION_DIR}/wait-for-cleanup.py" --kubeconfig "${PROVIDER_DATALAB_KUBECONFIG}" \
      --context "${KUBECTL_CONTEXT}" --datalab verify-vcluster
    stop_unused_operator cnpg-system cnpg clusters.postgresql.cnpg.io
  fi
}
main "$@"
