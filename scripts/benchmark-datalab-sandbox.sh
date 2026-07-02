#!/usr/bin/env bash
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

CLUSTER_NAME="${CLUSTER_NAME:-provider-datalab-netpol-e2e}"
KIND_IMAGE="${KIND_IMAGE:-kindest/node:v1.35.0}"
POD_CIDR="${POD_CIDR:-192.168.0.0/16}"
SERVICE_CIDR="${SERVICE_CIDR:-10.96.0.0/12}"
CALICO_VERSION="${CALICO_VERSION:-v3.32.0}"
CALICO_MANIFEST_URL="${CALICO_MANIFEST_URL:-https://raw.githubusercontent.com/projectcalico/calico/${CALICO_VERSION}/manifests/calico.yaml}"
KYVERNO_CHART_VERSION="${KYVERNO_CHART_VERSION:-3.8.1}"
CLIENT_IMAGE="${CLIENT_IMAGE:-curlimages/curl:8.10.1}"
SERVER_IMAGE="${SERVER_IMAGE:-nginx:1.27-alpine}"
EXTERNAL_URL="${EXTERNAL_URL:-https://example.com}"
ITERATIONS="${ITERATIONS:-3}"
RECREATE_CLUSTER="${RECREATE_CLUSTER:-0}"
KEEP_CLUSTER="${KEEP_CLUSTER:-1}"
RESULTS_FILE="${RESULTS_FILE:-/tmp/provider-datalab-sandbox-benchmark.tsv}"

NS_OPEN="pdla-egress-open"
NS_CLOSED="pdla-egress-closed"
NS_PEER="pdla-peer"

PASS_COUNT=0
FAIL_COUNT=0
CREATED_CLUSTER=0

log() {
  printf '[provider-datalab-benchmark] %s\n' "$*"
}

require_cmd() {
  command -v "$1" >/dev/null || {
    printf 'missing required command: %s\n' "$1" >&2
    exit 1
  }
}

kind_exists() {
  kind get clusters | grep -qx "$CLUSTER_NAME"
}

cleanup() {
  if [[ "$KEEP_CLUSTER" != "1" && "$CREATED_CLUSTER" == "1" ]]; then
    log "deleting kind cluster ${CLUSTER_NAME}"
    kind delete cluster --name "$CLUSTER_NAME" >/dev/null
  fi
}
trap cleanup EXIT

create_or_select_cluster() {
  if kind_exists; then
    if [[ "$RECREATE_CLUSTER" == "1" ]]; then
      log "recreating kind cluster ${CLUSTER_NAME}"
      kind delete cluster --name "$CLUSTER_NAME" >/dev/null
    else
      log "using existing kind cluster ${CLUSTER_NAME}"
      kind export kubeconfig --name "$CLUSTER_NAME" >/dev/null
      kubectl config use-context "kind-${CLUSTER_NAME}" >/dev/null
      return
    fi
  fi

  log "creating kind cluster ${CLUSTER_NAME} with default CNI disabled"
  cat <<EOF | kind create cluster --name "$CLUSTER_NAME" --image "$KIND_IMAGE" --config=-
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
networking:
  disableDefaultCNI: true
  podSubnet: "${POD_CIDR}"
  serviceSubnet: "${SERVICE_CIDR}"
nodes:
- role: control-plane
EOF
  CREATED_CLUSTER=1
}

install_calico() {
  log "installing Calico ${CALICO_VERSION} for NetworkPolicy enforcement"
  kubectl apply -f "$CALICO_MANIFEST_URL" >/dev/null
  kubectl -n kube-system rollout status daemonset/calico-node --timeout=300s >/dev/null
  kubectl -n kube-system rollout status deployment/calico-kube-controllers --timeout=300s >/dev/null
  kubectl wait --for=condition=Ready nodes --all --timeout=300s >/dev/null
}

install_kyverno() {
  log "installing Kyverno chart ${KYVERNO_CHART_VERSION}"
  helm repo add kyverno https://kyverno.github.io/kyverno/ >/dev/null 2>&1 || true
  helm repo update kyverno >/dev/null
  helm upgrade --install kyverno kyverno/kyverno \
    --namespace kyverno \
    --create-namespace \
    --version "$KYVERNO_CHART_VERSION" \
    --wait \
    --timeout 8m >/dev/null
}

apply_kyverno_policy() {
  log "applying Kyverno host/privilege guard policy"
  kubectl apply -f - <<EOF >/dev/null
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: datalab-benchmark-disallow-host-and-privileged-access
spec:
  validationFailureAction: Enforce
  background: false
  rules:
  - name: no-host-or-privileged-pods
    match:
      any:
      - resources:
          kinds:
          - Pod
          namespaces:
          - ${NS_OPEN}
          - ${NS_CLOSED}
          - ${NS_PEER}
    validate:
      message: "Datalab benchmark namespaces must not use host namespaces, hostPath volumes, or privileged containers."
      pattern:
        spec:
          =(hostNetwork): false
          =(hostPID): false
          =(hostIPC): false
          =(volumes):
          - X(hostPath): "null"
          containers:
          - =(securityContext):
              =(privileged): false
EOF
}

apply_namespaces() {
  log "creating benchmark namespaces"
  for ns in "$NS_OPEN" "$NS_CLOSED" "$NS_PEER"; do
    kubectl create namespace "$ns" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  done
}

apply_servers() {
  log "creating namespace-local and peer HTTP targets"
  for ns in "$NS_OPEN" "$NS_CLOSED" "$NS_PEER"; do
    kubectl -n "$ns" apply -f - <<EOF >/dev/null
apiVersion: apps/v1
kind: Deployment
metadata:
  name: echo
spec:
  replicas: 1
  selector:
    matchLabels:
      app: echo
  template:
    metadata:
      labels:
        app: echo
    spec:
      containers:
      - name: nginx
        image: ${SERVER_IMAGE}
        imagePullPolicy: IfNotPresent
        ports:
        - containerPort: 80
---
apiVersion: v1
kind: Service
metadata:
  name: echo
spec:
  selector:
    app: echo
  ports:
  - name: http
    port: 80
    targetPort: 80
EOF
    kubectl -n "$ns" rollout status deployment/echo --timeout=180s >/dev/null
  done
}

apply_clients() {
  log "creating curl clients"
  for ns in "$NS_OPEN" "$NS_CLOSED"; do
    kubectl -n "$ns" delete pod client --ignore-not-found --wait=true >/dev/null
    kubectl -n "$ns" run client \
      --image="$CLIENT_IMAGE" \
      --image-pull-policy=IfNotPresent \
      --restart=Never \
      --command -- sleep 3600 >/dev/null
    kubectl -n "$ns" wait --for=condition=Ready pod/client --timeout=180s >/dev/null
  done
}

apply_datalab_policies() {
  local ns="$1"
  local external_egress="$2"

  kubectl -n "$ns" apply -f - <<EOF >/dev/null
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: deny-egress
spec:
  podSelector: {}
  policyTypes:
  - Egress
  egress: []
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-namespace-egress
spec:
  podSelector: {}
  policyTypes:
  - Egress
  egress:
  - to:
    - podSelector: {}
EOF

  if [[ "$external_egress" == "true" ]]; then
    kubectl -n "$ns" apply -f - <<EOF >/dev/null
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-dns-egress
spec:
  podSelector: {}
  policyTypes:
  - Egress
  egress:
  - to:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: kube-system
    ports:
    - protocol: UDP
      port: 53
    - protocol: TCP
      port: 53
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-external-egress
spec:
  podSelector: {}
  policyTypes:
  - Egress
  egress:
  - to:
    - ipBlock:
        cidr: 0.0.0.0/0
        except:
        - 169.254.169.254/32
        - 169.254.42.42/32
        - ${POD_CIDR}
        - ${SERVICE_CIDR}
  - to:
    - ipBlock:
        cidr: ::/0
        except:
        - fd00:ec2::254/128
        - fd00:42::42/128
EOF
  fi
}

apply_network_policies() {
  log "applying Datalab-style NetworkPolicy modes"
  apply_datalab_policies "$NS_OPEN" true
  apply_datalab_policies "$NS_CLOSED" false
}

pod_ip() {
  kubectl -n "$1" get pod -l app=echo -o jsonpath='{.items[0].status.podIP}'
}

service_ip() {
  kubectl -n "$1" get svc echo -o jsonpath='{.spec.clusterIP}'
}

record_result() {
  local category="$1"
  local name="$2"
  local iteration="$3"
  local expected="$4"
  local observed="$5"
  local duration_ms="$6"
  local exit_code="$7"

  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$category" "$name" "$iteration" "$expected" "$observed" "$duration_ms" "$exit_code" >> "$RESULTS_FILE"

  if [[ "$observed" == "PASS" ]]; then
    PASS_COUNT=$((PASS_COUNT + 1))
  else
    FAIL_COUNT=$((FAIL_COUNT + 1))
  fi

  printf '%-12s %-42s iter=%-2s expected=%-7s observed=%-4s duration_ms=%s exit=%s\n' \
    "$category" "$name" "$iteration" "$expected" "$observed" "$duration_ms" "$exit_code"
}

run_exec_case() {
  local name="$1"
  local ns="$2"
  local expected="$3"
  local command="$4"
  local i start end duration exit_code observed

  for ((i = 1; i <= ITERATIONS; i++)); do
    start=$(date +%s%3N)
    set +e
    kubectl -n "$ns" exec client -- sh -c "$command" >/tmp/provider-datalab-benchmark-last.log 2>&1
    exit_code=$?
    set -e
    end=$(date +%s%3N)
    duration=$((end - start))

    if [[ "$expected" == "allow" && "$exit_code" == "0" ]]; then
      observed="PASS"
    elif [[ "$expected" == "block" && "$exit_code" != "0" ]]; then
      observed="PASS"
    else
      observed="FAIL"
      log "last output for ${name}: $(tr '\n' ' ' </tmp/provider-datalab-benchmark-last.log | cut -c1-300)"
    fi

    record_result "network" "$name" "$i" "$expected" "$observed" "$duration" "$exit_code"
  done
}

run_apply_denied_case() {
  local name="$1"
  local manifest="$2"
  local start end duration exit_code observed

  start=$(date +%s%3N)
  set +e
  printf '%s\n' "$manifest" | kubectl apply -f - >/tmp/provider-datalab-benchmark-last.log 2>&1
  exit_code=$?
  set -e
  end=$(date +%s%3N)
  duration=$((end - start))

  if [[ "$exit_code" != "0" ]]; then
    observed="PASS"
  else
    observed="FAIL"
    kubectl -n "$NS_OPEN" delete pod should-be-denied --ignore-not-found >/dev/null 2>&1 || true
  fi

  record_result "admission" "$name" 1 "block" "$observed" "$duration" "$exit_code"
}

require_fixture_contains() {
  local file="$1"
  local pattern="$2"
  local description="$3"

  if ! grep -q -- "$pattern" "$file"; then
    printf 'fixture contract failed: %s must contain %s (%s)\n' "$file" "$pattern" "$description" >&2
    exit 1
  fi
}

require_fixture_absent() {
  local file="$1"
  local pattern="$2"
  local description="$3"

  if grep -q -- "$pattern" "$file"; then
    printf 'fixture contract failed: %s must not contain %s (%s)\n' "$file" "$pattern" "$description" >&2
    exit 1
  fi
}

validate_external_egress_fixture() {
  local file="$1"

  require_fixture_contains "$file" 'name: deny-egress' "default-deny egress baseline"
  require_fixture_contains "$file" 'name: allow-namespace-egress' "same-namespace egress allow"
  require_fixture_contains "$file" 'name: allow-dns-egress' "DNS egress allow"
  require_fixture_contains "$file" 'name: allow-external-egress' "external egress allow"
  require_fixture_contains "$file" '169.254.169.254/32' "AWS metadata block"
  require_fixture_contains "$file" '169.254.42.42/32' "Scaleway metadata block"
  require_fixture_contains "$file" 'fd00:ec2::254/128' "AWS IPv6 metadata block"
  require_fixture_contains "$file" 'fd00:42::42/128' "Scaleway IPv6 metadata block"
  require_fixture_contains "$file" '10.42.0.0/16' "cluster pod CIDR exclusion"
  require_fixture_contains "$file" '10.43.0.0/16' "cluster service CIDR exclusion"
  require_fixture_absent "$file" 'name: allow-web-egress' "legacy broad egress policy"
}

validate_default_environment_fixture() {
  local file="$1"

  validate_external_egress_fixture "$file"
  require_fixture_contains "$file" 'name: allow-internal-egress' "explicit internal backend allow"
  require_fixture_contains "$file" 'v1.min.io/tenant: default' "MinIO backend selector"
  require_fixture_contains "$file" 'namespace: minio' "MinIO backend namespace"
}

validate_no_external_egress_fixture() {
  local file="$1"

  require_fixture_contains "$file" 'name: deny-egress' "default-deny egress baseline"
  require_fixture_contains "$file" 'name: allow-namespace-egress' "same-namespace egress allow"
  require_fixture_contains "$file" 'name: allow-internal-egress' "explicit internal backend allow"
  require_fixture_absent "$file" 'name: allow-dns-egress' "DNS egress must be disabled with externalEgress=false"
  require_fixture_absent "$file" 'name: allow-external-egress' "external egress must be disabled with externalEgress=false"
  require_fixture_absent "$file" 'name: allow-web-egress' "legacy broad egress policy"
}

validate_rendered_contract() {
  if [[ ! -f educates/tests/expected/001-lab.yaml ]]; then
    return
  fi

  log "checking rendered NetworkPolicy fixture contract"
  validate_external_egress_fixture educates/tests/expected/001-lab.yaml
  validate_no_external_egress_fixture educates/tests/expected/002-lab.yaml
  validate_default_environment_fixture educates/tests/expected/003-lab.yaml
  validate_default_environment_fixture educates/tests/expected/004-lab.yaml
}

print_summary() {
  log "benchmark result file: ${RESULTS_FILE}"
  awk -F '\t' '
    NR == 1 { next }
    {
      key=$1 ":" $2;
      count[key]++;
      sum[key]+=$6;
      if ($5 != "PASS") failed[key]++;
    }
    END {
      printf "\n%-12s %-42s %-8s %-12s\n", "category", "case", "avg_ms", "failures";
      for (key in count) {
        split(key, parts, ":");
        printf "%-12s %-42s %-8.1f %-12d\n", parts[1], parts[2], sum[key]/count[key], failed[key]+0;
      }
    }
  ' "$RESULTS_FILE"
  printf '\nTotals: PASS=%s FAIL=%s\n' "$PASS_COUNT" "$FAIL_COUNT"
}

main() {
  require_cmd docker
  require_cmd kind
  require_cmd kubectl
  require_cmd helm
  require_cmd awk

  validate_rendered_contract
  create_or_select_cluster
  install_calico
  install_kyverno
  apply_namespaces
  apply_kyverno_policy
  apply_servers
  apply_clients
  apply_network_policies

  printf 'category\tcase\titeration\texpected\tobserved\tduration_ms\texit_code\n' > "$RESULTS_FILE"

  local open_pod open_svc closed_pod closed_svc peer_pod peer_svc
  open_pod=$(pod_ip "$NS_OPEN")
  open_svc=$(service_ip "$NS_OPEN")
  closed_pod=$(pod_ip "$NS_CLOSED")
  closed_svc=$(service_ip "$NS_CLOSED")
  peer_pod=$(pod_ip "$NS_PEER")
  peer_svc=$(service_ip "$NS_PEER")

  log "open pod=${open_pod} service=${open_svc}; closed pod=${closed_pod} service=${closed_svc}; peer pod=${peer_pod} service=${peer_svc}"

  run_exec_case "open same-namespace PodIP" "$NS_OPEN" allow "curl -fsS --connect-timeout 2 --max-time 5 http://${open_pod}/ >/dev/null"
  run_exec_case "open same-namespace ServiceIP" "$NS_OPEN" allow "curl -fsS --connect-timeout 2 --max-time 5 http://${open_svc}/ >/dev/null"
  run_exec_case "open cross-namespace PodIP" "$NS_OPEN" block "curl -fsS --connect-timeout 2 --max-time 5 http://${peer_pod}/ >/dev/null"
  run_exec_case "open cross-namespace ServiceIP" "$NS_OPEN" block "curl -fsS --connect-timeout 2 --max-time 5 http://${peer_svc}/ >/dev/null"
  run_exec_case "open AWS metadata IPv4" "$NS_OPEN" block "curl -fsS --connect-timeout 2 --max-time 5 http://169.254.169.254/ >/dev/null"
  run_exec_case "open Scaleway metadata IPv4" "$NS_OPEN" block "curl -fsS --connect-timeout 2 --max-time 5 http://169.254.42.42/ >/dev/null"
  run_exec_case "open Scaleway metadata IPv6" "$NS_OPEN" block "curl -g -fsS --connect-timeout 2 --max-time 5 'http://[fd00:42::42]/' >/dev/null"
  run_exec_case "open external URL" "$NS_OPEN" allow "curl -fsS --connect-timeout 5 --max-time 15 ${EXTERNAL_URL} >/dev/null"

  run_exec_case "closed same-namespace PodIP" "$NS_CLOSED" allow "curl -fsS --connect-timeout 2 --max-time 5 http://${closed_pod}/ >/dev/null"
  run_exec_case "closed same-namespace ServiceIP" "$NS_CLOSED" allow "curl -fsS --connect-timeout 2 --max-time 5 http://${closed_svc}/ >/dev/null"
  run_exec_case "closed cross-namespace PodIP" "$NS_CLOSED" block "curl -fsS --connect-timeout 2 --max-time 5 http://${peer_pod}/ >/dev/null"
  run_exec_case "closed cross-namespace ServiceIP" "$NS_CLOSED" block "curl -fsS --connect-timeout 2 --max-time 5 http://${peer_svc}/ >/dev/null"
  run_exec_case "closed external URL" "$NS_CLOSED" block "curl -fsS --connect-timeout 5 --max-time 15 ${EXTERNAL_URL} >/dev/null"

  run_exec_case "normal pod has no Docker socket" "$NS_OPEN" allow "test ! -S /var/run/docker.sock"
  run_exec_case "normal pod has no host root mount" "$NS_OPEN" allow "test ! -e /host/etc/shadow"

  run_apply_denied_case "deny privileged container" "$(cat <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: should-be-denied
  namespace: ${NS_OPEN}
spec:
  restartPolicy: Never
  containers:
  - name: denied
    image: busybox:1.36.1
    command: ["sh", "-c", "sleep 1"]
    securityContext:
      privileged: true
EOF
)"

  run_apply_denied_case "deny hostNetwork" "$(cat <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: should-be-denied
  namespace: ${NS_OPEN}
spec:
  hostNetwork: true
  restartPolicy: Never
  containers:
  - name: denied
    image: busybox:1.36.1
    command: ["sh", "-c", "sleep 1"]
EOF
)"

  run_apply_denied_case "deny docker socket hostPath" "$(cat <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: should-be-denied
  namespace: ${NS_OPEN}
spec:
  restartPolicy: Never
  containers:
  - name: denied
    image: busybox:1.36.1
    command: ["sh", "-c", "sleep 1"]
    volumeMounts:
    - name: docker-sock
      mountPath: /var/run/docker.sock
  volumes:
  - name: docker-sock
    hostPath:
      path: /var/run/docker.sock
      type: Socket
EOF
)"

  print_summary

  if [[ "$FAIL_COUNT" != "0" ]]; then
    exit 1
  fi
}

main "$@"
