#!/usr/bin/env bash
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

set -Eeuo pipefail
INTEGRATION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${INTEGRATION_DIR}/lib.bash"
source "${INTEGRATION_DIR}/educates.bash"
source "${INTEGRATION_DIR}/postgres.bash"
: "${EDUCATES_DEPENDENCIES_VERSION:=2.2.1}"
: "${KEEP_VCLUSTER_RESOURCES:=0}"
readonly EDUCATES_NAMESPACE=educates
readonly VCLUSTER_NAMESPACE=verify-vcluster
readonly CONTOUR_VERSION=v1.33.7
work_directory="$(mktemp -d /tmp/datalab-vcluster.XXXXXX)"
trap 'rm -rf "${work_directory}"' EXIT

report_failure() {
  local result=$?
  trap - ERR
  kube get datalab/verify-vcluster --namespace workspace || true
  kube get datalab/s-john datalab/s-jane --namespace workspace || true
  kube get objects.kubernetes.m.crossplane.io --namespace workspace --selector crossplane.io/composite=verify-vcluster || true
  kube get statefulsets,pods,httproutes,backendtlspolicies --namespace "${VCLUSTER_NAMESPACE}" || true
  kube get events --namespace "${VCLUSTER_NAMESPACE}" --sort-by=.lastTimestamp | tail -25 || true
  kube logs statefulset/vcluster-vc0 --namespace "${VCLUSTER_NAMESPACE}" --tail=40 || true
  printf 'vCluster resources were kept for diagnosis.\n' >&2
  exit "${result}"
}
trap report_failure ERR

build_catalog_image() {
  local digest
  digest="$(cat "${REPO_ROOT}/tests/vcluster/"{catalog.Dockerfile,migrate.py} | sha256sum | cut -c1-16)"
  catalog_image="datalab-stac:${digest}"
  mkdir -p "${work_directory}/docker" "${work_directory}/build/tests/vcluster"
  cp "${REPO_ROOT}/tests/vcluster/migrate.py" "${work_directory}/build/tests/vcluster/"
  if ! DOCKER_CONFIG="${work_directory}/docker" docker image inspect "${catalog_image}" >/dev/null 2>&1; then
    DOCKER_CONFIG="${work_directory}/docker" docker build --provenance=false --tag "${catalog_image}" \
      --file "${REPO_ROOT}/tests/vcluster/catalog.Dockerfile" "${work_directory}/build"
  fi
  if ! docker exec "${KIND_CLUSTER_NAME}-control-plane" crictl inspecti "docker.io/library/${catalog_image}" >/dev/null 2>&1; then
    DOCKER_CONFIG="${work_directory}/docker" KUBECONFIG="${PROVIDER_DATALAB_KUBECONFIG}" kind load docker-image "${catalog_image}" --name "${KIND_CLUSTER_NAME}"
  fi
  python3 - "${REPO_ROOT}/examples/vcluster/stac-fastapi.yaml" "${catalog_image}" >"${work_directory}/catalog.json" <<'CATALOG'
import json, sys, yaml
from pathlib import Path
print(json.dumps(list(yaml.safe_load_all(Path(sys.argv[1]).read_text().replace('__CATALOG_IMAGE__', sys.argv[2])))))
CATALOG
}

install_prerequisites() {
  create_ingress_certificate
  install_educates
  install_pgo
  mkdir -p "${PROVIDER_DATALAB_HELM_HOME}"
  local contour_manifest="${PROVIDER_DATALAB_HELM_HOME}/contour-${CONTOUR_VERSION}.yaml"
  if [[ ! -s "${contour_manifest}" ]]; then
    curl --fail --silent --show-error --location \
      "https://raw.githubusercontent.com/projectcontour/contour/${CONTOUR_VERSION}/examples/render/contour-gateway-provisioner.yaml" \
      --output "${contour_manifest}"
  fi
  kube apply --server-side -f "${contour_manifest}"
  wait_for_crd_established httproutes.gateway.networking.k8s.io
  wait_for_crd_established backendtlspolicies.gateway.networking.k8s.io
  kube rollout status deployment/contour-gateway-provisioner --namespace projectcontour --timeout=10m
  kube get secret/verify-vcluster-gateway-tls --namespace projectcontour -o jsonpath='{.data.tls\.crt}' 2>/dev/null \
    | base64 --decode >"${work_directory}/gateway.crt" || true
  if ! openssl x509 -in "${work_directory}/gateway.crt" -checkend 600 -noout >/dev/null 2>&1; then
    openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj '/CN=*.lab.acme.com' \
      -addext 'subjectAltName=DNS:*.lab.acme.com' \
      -keyout "${work_directory}/gateway.key" -out "${work_directory}/gateway.crt" >/dev/null 2>&1
    kube create secret tls verify-vcluster-gateway-tls --namespace projectcontour \
      --cert "${work_directory}/gateway.crt" --key "${work_directory}/gateway.key" \
      --dry-run=client -o yaml | kube apply -f -
  fi
  kube apply -f "${MANIFEST_DIR}/vcluster/gateway.yaml"
  if ! kube get deployment/keycloak --namespace keycloak >/dev/null 2>&1; then
    kube apply -f "${MANIFEST_DIR}/s3/keycloak.yaml"
  fi
  kube get secret/verify-vcluster-issuer --namespace keycloak -o jsonpath='{.data.tls\.crt}' 2>/dev/null \
    | base64 --decode >"${work_directory}/issuer.crt" || true
  if ! openssl x509 -in "${work_directory}/issuer.crt" -checkend 600 -noout >/dev/null 2>&1; then
    openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj '/CN=keycloak.keycloak' \
      -addext 'subjectAltName=DNS:keycloak.keycloak' \
      -keyout "${work_directory}/issuer.key" -out "${work_directory}/issuer.crt" >/dev/null 2>&1
    kube create secret tls verify-vcluster-issuer --namespace keycloak \
      --cert "${work_directory}/issuer.crt" --key "${work_directory}/issuer.key" \
      --dry-run=client -o yaml | kube apply -f -
  fi
  kube patch deployment/keycloak --namespace keycloak --type=strategic --patch "$(
    jq -n --arg checksum "$(sha256sum "${work_directory}/issuer.crt" | cut -d' ' -f1)" '{spec:{template:{
      metadata:{annotations:{"datalabs.pkg.internal/issuer-checksum":$checksum}},
      spec:{containers:[{name:"keycloak",args:["start-dev","--import-realm","--https-certificate-file=/tls/tls.crt","--https-certificate-key-file=/tls/tls.key"],
        volumeMounts:[{name:"tls",mountPath:"/tls",readOnly:true}]}],
        volumes:[{name:"tls",secret:{secretName:"verify-vcluster-issuer"}}]}}}}'
  )"
  kube patch service/keycloak --namespace keycloak --type=strategic \
    --patch '{"spec":{"ports":[{"name":"https","port":8443,"targetPort":8443}]}}'
  kube rollout status deployment/keycloak --namespace keycloak --timeout=10m
  kube wait gateway/verify-vcluster --namespace projectcontour --for=condition=Programmed --timeout=10m
  kube wait deployment --namespace projectcontour --selector gateway.networking.k8s.io/gateway-name=verify-vcluster \
    --for=condition=Available --timeout=10m
  kube apply -f "${MANIFEST_DIR}/vcluster/environmentconfig.yaml"
  kube patch environmentconfig/datalab-vcluster-it --type=merge \
    --patch "$(jq -n --rawfile ca "${work_directory}/issuer.crt" --rawfile gateway_ca "${work_directory}/gateway.crt" '{data:{vcluster:{issuerCA:$ca},ingress:{certificateAuthority:$gateway_ca}}}')"
}


verify_custom_connections() {
  local team namespace key deadline expected
  kube patch environmentconfig/datalab-custom --type=merge --patch \
    '{"data":{"customSecrets":[{"name":"apikey-1"},{"name":"apikey-2"}],"defaults":{"data":{"enabled":false},"registry":{"enabled":false},"vcluster":{"enabled":false}}}}'
  for team in s-john s-jane; do
    kube create secret generic "${team}" --namespace workspace \
      --from-literal=AWS_ACCESS_KEY_ID=minioadmin --from-literal=AWS_SECRET_ACCESS_KEY=minioadmin \
      --dry-run=client -o yaml | kube apply -f -
    kube apply -f - <<DATALAB
apiVersion: pkg.internal/v1beta2
kind: Datalab
metadata:
  name: ${team}
  namespace: workspace
  annotations:
    datalabs.pkg.internal/environment: datalab-custom
spec:
  users: [verify-s3]
  sessions: []
DATALAB
  done
  for team in s-john s-jane; do
    namespace="$(wait_for_runtime_namespace "${team}")"
    [[ "${namespace}" == "${team}" ]]
    kube wait "datalab/${team}" --namespace workspace --for=condition=Ready --timeout=10m
    kube get "datalab/${team}" --namespace workspace -o json \
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
    until kube get "datalab/${team}" --namespace workspace -o json | jq -e --argjson expected "${expected}" \
      '([.status.connections[]? | select(.type == "custom") | .name] | sort) == $expected and all(.status.connections[]?; .ready)' >/dev/null; do
      ((SECONDS < deadline)) || return 1
      sleep 2
    done
    kube wait "datalab/${team}" --namespace workspace --for=condition=Ready --timeout=5m
    python3 "${INTEGRATION_DIR}/verify-service-connections.py" \
      --kubeconfig "${PROVIDER_DATALAB_KUBECONFIG}" --namespace workspace --datalab "${team}"
  done
  printf 'PASS John has both custom keys; Jane has only apikey-1; missing keys do not block readiness\n'
  if [[ "${KEEP_VCLUSTER_RESOURCES}" != 1 ]]; then
    kube delete datalab/s-john datalab/s-jane --namespace workspace --wait=false
    for team in s-john s-jane; do
      kube wait "datalab/${team}" --namespace workspace --for=delete --timeout=10m
      python3 "${INTEGRATION_DIR}/verify-service-connections.py" \
        --kubeconfig "${PROVIDER_DATALAB_KUBECONFIG}" --namespace workspace --datalab "${team}" --deleted
      kube wait "namespace/${team}" --for=delete --timeout=10m
    done
    kube delete secret/s-john secret/s-jane --namespace workspace
  fi
}

verify_vcluster() {
  local service gateway_ip deadline administrator_secret editor_secret other_secret
  kube apply -f "${MANIFEST_DIR}/vcluster/datalab.yaml"
  runtime_namespace="$(wait_for_runtime_namespace verify-vcluster)"
  [[ "${runtime_namespace}" == "${VCLUSTER_NAMESPACE}" ]]
  kube apply -f "${MANIFEST_DIR}/vcluster/postgres-network.yaml"
  for instance in vc0 vc1; do
    kube wait "statefulset/vcluster-${instance}" --namespace "${runtime_namespace}" --for=create --timeout=10m
    kube rollout status "statefulset/vcluster-${instance}" --namespace "${runtime_namespace}" --timeout=15m
  done
  kube wait postgrescluster/pg0 --namespace "${runtime_namespace}" --for=create --timeout=10m
  deadline=$((SECONDS + 900))
  until kube get postgrescluster/pg0 --namespace "${runtime_namespace}" -o json | jq -e 'any(.status.instances[]?; .readyReplicas >= 1)' >/dev/null; do
    ((SECONDS < deadline)) || return 1
    sleep 5
  done
  wait_for_connection_secret verify-vcluster-datalab verify-vcluster 600 POSTGRES_PG0_PASSWORD POSTGRES_PG0_HOST
  connection_secret() {
    kube get datalab/verify-vcluster --namespace workspace -o json | jq -er --arg instance "$1" --arg group "$2" \
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
  kube wait datalab/verify-vcluster --namespace workspace --for=condition=Ready --timeout=15m
  kube get datalab/verify-vcluster --namespace workspace -o json | python3 -c '
import json, sys
status = json.load(sys.stdin)["status"]
assert status["oauth2"] == [{"name": "verify-vcluster", "type": "client", "issuerUrl": "https://keycloak.keycloak:8443/realms/integration", "secretRef": {"name": "verify-vcluster-oauth-client", "namespace": "workspace"}, "ready": True}]
assert not any(c["type"] == "oauth2" for c in status["connections"])
connections = [c for c in status["connections"] if c["type"] == "vcluster"]
assert len(connections) == 4 and all(c["ready"] for c in connections)
assert {c["instance"] for c in connections} == {"vc0", "vc1"}
assert all(set(c) <= {"name", "type", "instance", "group", "targetNamespace", "role", "endpoint", "ready", "secretRef"} for c in connections)
print("PASS connection status contains ready profile references without credentials")'
  if kube patch datalab/verify-vcluster --namespace workspace --subresource=status --dry-run=server --type=merge \
    --patch '{"status":{"oauth2":[{"name":"duplicate","type":"client","issuerUrl":"https://identity.example","secretRef":{"name":"test","namespace":"workspace"},"ready":false},{"name":"duplicate","type":"client","issuerUrl":"https://identity.example","secretRef":{"name":"test","namespace":"workspace"},"ready":false}]}}' \
    >"${work_directory}/oauth-admission.log" 2>&1; then
    printf 'Kubernetes admitted duplicate OAuth2 discovery names.\n' >&2
    return 1
  fi
  grep -F 'Duplicate value' "${work_directory}/oauth-admission.log" >/dev/null
  printf 'PASS OAuth2 discovery is separate and Kubernetes rejects duplicate client names\n'
  python3 "${INTEGRATION_DIR}/verify-oauth-discovery.py" \
    --kubeconfig "${PROVIDER_DATALAB_KUBECONFIG}" --datalab verify-vcluster
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
    --dry-run=client -o yaml | kube apply -f -
  kube delete pod/verify-vcluster-client --namespace workspace --ignore-not-found --wait=true
  apply_template "${MANIFEST_DIR}/vcluster/client.yaml" \
    ADMINISTRATOR_SECRET "${administrator_secret}" EDITOR_SECRET "${editor_secret}" OTHER_SECRET "${other_secret}"
  kube wait pod/verify-vcluster-client --namespace workspace --for=condition=Ready --timeout=5m
  cp -L "$(command -v kubectl)" "${work_directory}/kubectl"
  kube cp "${work_directory}/kubectl" workspace/verify-vcluster-client:/tmp/kubectl
  kube exec verify-vcluster-client --namespace workspace -- python3 -u /test/e2e.py "${gateway_ip}" --member-roles
  kube patch datalab/verify-vcluster --namespace workspace --type=merge --patch '{"spec":{"users":[]}}'
  kube exec verify-vcluster-client --namespace workspace -- python3 -u /test/e2e.py "${gateway_ip}" --member-removed
  kube patch datalab/verify-vcluster --namespace workspace --type=merge --patch '{"spec":{"users":["verify-s3","verify-vcluster-member"]}}'
  kube exec verify-vcluster-client --namespace workspace -- python3 -u /test/e2e.py "${gateway_ip}" --member-roles
  kube exec verify-vcluster-client --namespace workspace -- python3 -u /test/e2e.py "${gateway_ip}"
  kube rollout restart statefulset/vcluster-vc0 --namespace "${runtime_namespace}"
  kube rollout status statefulset/vcluster-vc0 --namespace "${runtime_namespace}" --timeout=10m
  kube exec verify-vcluster-client --namespace workspace -- python3 -u /test/e2e.py "${gateway_ip}" --check-only
  kube patch datalab/verify-vcluster --namespace workspace --type=json \
    --patch '[{"op":"replace","path":"/spec/vclusters/vc0/groups/0/role","value":"view"}]'
  kube exec verify-vcluster-client --namespace workspace -- python3 -u /test/e2e.py "${gateway_ip}" --read-only
  kube patch datalab/verify-vcluster --namespace workspace --type=json \
    --patch '[{"op":"remove","path":"/spec/vclusters/vc0/groups/0"}]'
  kube exec verify-vcluster-client --namespace workspace -- python3 -u /test/e2e.py "${gateway_ip}" --revoked
  kube wait "secret/${editor_secret}" --namespace workspace --for=delete --timeout=5m
  kube patch datalab/verify-vcluster --namespace workspace --type=json --patch '[{"op":"remove","path":"/spec/vclusters/vc0"}]'
  kube wait statefulset/vcluster-vc0 --namespace "${runtime_namespace}" --for=delete --timeout=10m
  kube exec verify-vcluster-client --namespace workspace -- python3 -u /test/e2e.py "${gateway_ip}" --other-only
  kube exec verify-vcluster-client --namespace workspace -- python3 -u /test/e2e.py "${gateway_ip}" --member-roles --member-instance vc1
  kube get postgrescluster/pg0 --namespace "${runtime_namespace}" -o json | jq -e 'any(.status.instances[]?; .readyReplicas >= 1)' >/dev/null
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
for version in ('v1beta2',):
    source['apiVersion'] = 'pkg.internal/' + version
    for field in ('vclusters', 'databases', 'documentStores', 'cacheStores'):
        for key in ('0bad', 'Bad', 'bad_name', 'bad-', 'a' * 64):
            value = deepcopy(source)
            config = next(iter(value['spec'][field].values())) if field in value['spec'] else {'type': 'mongo' if field == 'documentStores' else 'redis', 'storage': '1Gi'}
            value['spec'][field] = {key: config}
            result = subprocess.run(['kubectl', '--kubeconfig', sys.argv[2], '--context', sys.argv[3], 'apply', '--dry-run=server', '-f', '-'], input=yaml.safe_dump(value), text=True, capture_output=True)
            assert result.returncode != 0 and 'Instance names must' in result.stderr, result.stderr
print('PASS Kubernetes admission rejects invalid instance names for all maps')
ADMISSION
}

main() {
  require_cluster
  install_prerequisites
  build_catalog_image
  verify_name_admission
  verify_custom_connections
  verify_vcluster
  if [[ "${KEEP_VCLUSTER_RESOURCES}" != 1 ]]; then
    kube delete pod/verify-vcluster-client configmap/verify-vcluster-client --namespace workspace --ignore-not-found
    kube delete datalab/verify-vcluster --namespace workspace --wait=false
    kube wait datalab/verify-vcluster --namespace workspace --for=delete --timeout=10m
    kube wait "namespace/${VCLUSTER_NAMESPACE}" --for=delete --timeout=10m
    stop_unused_operator postgres-operator pgo postgresclusters.postgres-operator.crunchydata.com
  fi
}
main "$@"
