#!/usr/bin/env bash
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

check_volume_snapshot_settings() {
  local namespace=${1:-verify-volumes} driver verb
  if [[ -z "${PROVIDER_DATALAB_SNAPSHOT_CLASS:-}" ]]; then
    printf 'No --snapshot-class was supplied.\n' >&2
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
  driver="$(kube get "storageclass/${PROVIDER_DATALAB_STORAGE_CLASS}" -o jsonpath='{.provisioner}')" || return 2
  [[ -n "${driver}" ]] || { printf 'The selected StorageClass has no provisioner.\n' >&2; return 2; }
  kube get "volumesnapshotclass/${PROVIDER_DATALAB_SNAPSHOT_CLASS}" -o json \
    | jq -e --arg driver "${driver}" '.driver == $driver and .deletionPolicy == "Delete"' >/dev/null || {
      printf 'The snapshot class must match the test CSI driver and use deletion policy Delete.\n' >&2
      return 2
    }
  if [[ "$(kube auth can-i get "volumesnapshotclasses.snapshot.storage.k8s.io/${PROVIDER_DATALAB_SNAPSHOT_CLASS}")" != yes ]]; then
    printf 'The test identity cannot read the selected VolumeSnapshotClass.\n' >&2
    return 2
  fi
  for verb in create get list delete; do
    if [[ "$(kube auth can-i "${verb}" volumesnapshots.snapshot.storage.k8s.io --namespace "${namespace}")" != yes ]]; then
      printf 'The test identity cannot %s VolumeSnapshots in %s.\n' "${verb}" "${namespace}" >&2
      return 2
    fi
  done
}

check_snapshot_observer_access() {
  local namespace=$1 resource verb account
  # Crossplane reads requested snapshots; the provider observes the class.
  for resource in volumesnapshots.snapshot.storage.k8s.io volumesnapshotclasses.snapshot.storage.k8s.io; do
    account=crossplane
    if [[ "${resource}" == volumesnapshotclasses.* ]]; then account=provider-kubernetes; fi
    for verb in get list watch; do
      if [[ "$(kube auth can-i "${verb}" "${resource}" --as "system:serviceaccount:crossplane:${account}" --namespace "${namespace}")" != yes ]]; then
        printf 'Snapshot observer %s cannot %s %s in %s.\n' "${account}" "${verb}" "${resource}" "${namespace}" >&2
        return 2
      fi
    done
  done
}

snapshot_tests_available() {
  local reason
  if reason="$(check_volume_snapshot_settings "${1:-verify-volumes}" 2>&1 \
    && check_snapshot_observer_access "${1:-verify-volumes}" 2>&1)"; then
    printf 'PASS %s snapshot API, class, and permission checks.\n' "${1:-verify-volumes}"
    return 0
  fi
  if [[ "${PROVIDER_DATALAB_CLUSTER}" == kind || -n "${PROVIDER_DATALAB_SNAPSHOT_CLASS:-}" ]]; then
    printf 'ERROR: Required snapshot setup is incomplete: %s\n' "${reason}" >&2
    exit 1
  fi
  printf '\n=== SKIPPED: %s snapshot tests: %s ===\n\n' "${1:-verify-volumes}" "${reason}"
  return 1
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
  kube get --raw=/apis/admissionregistration.k8s.io/v1 \
    | jq -e '.resources | map(.name) | contains(["mutatingadmissionpolicies", "mutatingadmissionpolicybindings"])' >/dev/null || {
      printf 'Volume bindings need Kubernetes 1.36 or later with stable mutating admission policies.\n' >&2
      return 2
    }
}
