#!/usr/bin/env bash
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

check_volume_snapshot_settings() {
  if [[ -z "${PROVIDER_DATALAB_SNAPSHOT_CLASS:-}" ]]; then
    printf 'Volume integration needs --snapshot-class for the selected CSI StorageClass.\n' >&2
    return 2
  fi
  if [[ -z "${PROVIDER_DATALAB_STORAGE_CLASS:-}" ]]; then
    printf 'Volume integration needs --storage-class for an existing snapshot-capable CSI driver.\n' >&2
    return 2
  fi
  kube get --raw=/apis/snapshot.storage.k8s.io/v1 \
    | jq -e '.resources | map(.name) | contains(["volumesnapshots", "volumesnapshotcontents", "volumesnapshotclasses"])' >/dev/null || {
      printf 'The selected cluster must already provide the CSI snapshot APIs and controller.\n' >&2
      return 2
    }
  local driver
  driver="$(kube get "storageclass/${PROVIDER_DATALAB_STORAGE_CLASS}" -o jsonpath='{.provisioner}')" || return 2
  [[ -n "${driver}" ]] || { printf 'The selected StorageClass has no provisioner.\n' >&2; return 2; }
  kube get "volumesnapshotclass/${PROVIDER_DATALAB_SNAPSHOT_CLASS}" -o json \
    | jq -e --arg driver "${driver}" '.driver == $driver and .deletionPolicy == "Delete"' >/dev/null || {
      printf 'The snapshot class must match the test CSI driver and use deletion policy Delete.\n' >&2
      return 2
    }
  local namespace=${1:-verify-volumes} verb
  for verb in create get list delete; do
    if [[ "$(kube auth can-i "${verb}" volumesnapshots.snapshot.storage.k8s.io --namespace "${namespace}")" != yes ]]; then
      printf 'The test identity cannot %s VolumeSnapshots in %s.\n' "${verb}" "${namespace}" >&2
      return 2
    fi
  done
}

check_volume_backup_access() {
  local namespace=$1 pvc=$2 account=$3 verb resource scope deadline request
  local identity="system:serviceaccount:${namespace}:${account}"
  local -a required=(
    "get persistentvolumeclaims/${pvc} ${namespace}"
    "get volumesnapshotclasses.snapshot.storage.k8s.io/${PROVIDER_DATALAB_SNAPSHOT_CLASS} ${namespace}"
    "create volumesnapshots.snapshot.storage.k8s.io ${namespace}"
    "get volumesnapshots.snapshot.storage.k8s.io ${namespace}"
    "list volumesnapshots.snapshot.storage.k8s.io ${namespace}"
    "delete volumesnapshots.snapshot.storage.k8s.io ${namespace}"
  )
  deadline=$((SECONDS + 120))
  for request in "${required[@]}"; do
    read -r verb resource scope <<<"${request}"
    until [[ "$(kube --request-timeout=10s auth can-i "${verb}" "${resource}" --namespace "${scope}" --as "${identity}")" == yes ]]; do
      if ((SECONDS >= deadline)); then
        printf 'Backup identity %s cannot %s %s in %s.\n' "${identity}" "${verb}" "${resource}" "${scope}" >&2
        return 1
      fi
      sleep 2
    done
  done
  local -a denied=(
    "get persistentvolumeclaims/test-other-volume ${namespace}"
    "delete persistentvolumeclaims/${pvc} ${namespace}"
    "list secrets ${namespace}"
    "create volumesnapshots.snapshot.storage.k8s.io default"
    "list volumesnapshots.snapshot.storage.k8s.io default"
    "delete volumesnapshots.snapshot.storage.k8s.io default"
    "get volumesnapshotcontents.snapshot.storage.k8s.io ${namespace}"
    "patch volumesnapshotclasses.snapshot.storage.k8s.io/${PROVIDER_DATALAB_SNAPSHOT_CLASS} ${namespace}"
  )
  for request in "${denied[@]}"; do
    read -r verb resource scope <<<"${request}"
    if [[ "$(kube --request-timeout=10s auth can-i "${verb}" "${resource}" --namespace "${scope}" --as "${identity}")" != no ]]; then
      printf 'Backup identity %s must not %s %s in %s.\n' "${identity}" "${verb}" "${resource}" "${scope}" >&2
      return 1
    fi
  done
  printf 'PASS snapshot backup permissions and access boundaries in %s\n' "${namespace}"
}

check_volume_binding_settings() {
  check_volume_snapshot_settings verify-vcluster || return
  kube get --raw=/apis/admissionregistration.k8s.io/v1 \
    | jq -e '.resources | map(.name) | contains(["mutatingadmissionpolicies", "mutatingadmissionpolicybindings"])' >/dev/null || {
      printf 'Volume bindings need Kubernetes 1.36 or later with stable mutating admission policies.\n' >&2
      return 2
    }
}
