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
}

check_volume_binding_settings() {
  check_volume_snapshot_settings || return
  kube get --raw=/apis/admissionregistration.k8s.io/v1 \
    | jq -e '.resources | map(.name) | contains(["mutatingadmissionpolicies", "mutatingadmissionpolicybindings"])' >/dev/null || {
      printf 'Volume bindings need Kubernetes 1.36 or later with stable mutating admission policies.\n' >&2
      return 2
    }
}
