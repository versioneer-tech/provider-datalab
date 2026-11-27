#!/usr/bin/env bash
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

set -Eeuo pipefail
INTEGRATION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${INTEGRATION_DIR}/lib.bash"
source "${INTEGRATION_DIR}/snapshots.bash"

if [[ "${PROVIDER_DATALAB_CLUSTER}" != kind || "${KUBECTL_CONTEXT}" != kind-provider-datalab-it ]]; then
  printf 'Storage setup is only available for the dedicated Kind cluster.\n' >&2
  exit 2
fi

diagnostics() {
  local result=$?
  trap - ERR
  kube get pods --namespace test-volume-snapshots -o wide || true
  kube get events --namespace test-volume-snapshots --sort-by=.lastTimestamp | tail -25 || true
  kube logs deployment/nfs-server --namespace test-volume-snapshots --tail=50 || true
  kube logs deployment/csi-nfs-controller --namespace test-volume-snapshots --container nfs --tail=50 || true
  printf 'Kind storage setup failed. Check NFS client support and the reported Pod events.\n' >&2
  exit "${result}"
}
trap diagnostics ERR

require_command helm
require_command jq
require_cluster

readonly driver_version=4.13.6
python3 "${REPO_ROOT}/scripts/components.py" snapshot-crds --manifest | \
  kube apply --server-side --field-manager=datalab-integration -f -
for resource in volumesnapshots volumesnapshotcontents volumesnapshotclasses; do
  wait_for_crd_established "${resource}.snapshot.storage.k8s.io"
done

kube apply -f "${MANIFEST_DIR}/volumes/nfs-server.yaml"
kube rollout status deployment/nfs-server --namespace test-volume-snapshots --timeout=5m

chart="$(python3 "${REPO_ROOT}/scripts/components.py" nfs-chart)"
helm_it upgrade --install datalab-nfs "${chart}" \
  --kubeconfig "${PROVIDER_DATALAB_KUBECONFIG}" --kube-context "${KUBECTL_CONTEXT}" \
  --namespace test-volume-snapshots --version "${driver_version}" \
  --post-renderer "${REPO_ROOT}/scripts/components.py" \
  --values "${MANIFEST_DIR}/volumes/nfs-values.yaml" --wait --timeout 10m
for deployment in csi-nfs-controller datalab-snapshot-controller; do
  kube rollout status "deployment/${deployment}" --namespace test-volume-snapshots --timeout=5m
done
kube rollout status daemonset/csi-nfs-node --namespace test-volume-snapshots --timeout=5m
kube --request-timeout=90s exec deployment/csi-nfs-controller --namespace test-volume-snapshots --container nfs -- sh -ec '
  directory="$(mktemp -d /tmp/test-nfs-client.XXXXXX)"
  trap '\''umount -l "$directory" 2>/dev/null || true; rmdir "$directory"'\'' EXIT
  timeout 45 mount -t nfs -o nfsvers=4.1,soft,timeo=20,retrans=2 \
    nfs-server.test-volume-snapshots.svc.cluster.local:/ "$directory"
  timeout 10 ls "$directory" >/dev/null
'
check_volume_snapshot_settings
printf 'Kind CSI storage and snapshot controllers are ready.\n'
