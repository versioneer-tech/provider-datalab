#!/usr/bin/env bash
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

for command_name in crossplane dyff docker; do
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    printf 'Missing required command: %s\n' "${command_name}" >&2
    exit 1
  fi
done

docker info >/dev/null

for file in examples/base/00*-lab.yaml; do
  name="$(basename "${file}")"
  index="${name#00}"
  index="${index%-lab.yaml}"
  actual="educates/tests/00${index}-lab.yaml"
  expected="educates/tests/expected/00${index}-lab.yaml"
  observed="educates/tests/observed/00${index}-lab.yaml"

  crossplane render \
    "${file}" \
    educates/composition.yaml \
    educates/dependencies/functions.yaml \
    --required-resources educates/tests/environmentconfig.yaml \
    -x \
    >"${actual}"

  dyff between "${actual}" "${expected}" -s

  if [[ -f "${observed}" ]]; then
    actual="educates/tests/00${index}x-lab.yaml"
    expected="educates/tests/expected/00${index}x-lab.yaml"

    crossplane render \
      "${file}" \
      educates/composition.yaml \
      educates/dependencies/functions.yaml \
      --required-resources educates/tests/environmentconfig.yaml \
      --observed-resources "${observed}" \
      -x \
      >"${actual}"

    dyff between "${actual}" "${expected}" -s
  fi
done

package_target_count="$(awk '/^  name: data-(deployment|dns-networkpolicy|networkpolicy|service)-s-joe$/ {count++} END {print count + 0}' educates/tests/001x-lab.yaml)"
runtime_secret_observer_count="$(awk '/^  name: observe-runtime-storage-secret-s-joe$/ {count++} END {print count + 0}' educates/tests/001x-lab.yaml)"

if [[ "${package_target_count}" != 4 || "${runtime_secret_observer_count}" != 1 ]]; then
  printf 'Expected four package-r targets and one runtime Secret observer.\n' >&2
  exit 1
fi

writable_permission_count="$(awk '/--perm\.(create|delete|modify|rename)=true/ {count++} END {print count + 0}' educates/tests/001x-lab.yaml)"
readonly_permission_count="$(awk '/--perm\.(create|delete|modify|rename)=/ {count++} END {print count + 0}' educates/tests/003x-lab.yaml)"

if [[ "${writable_permission_count}" != 2 || "${readonly_permission_count}" != 0 ]]; then
  printf 'Expected write flags for both writable Data users and none for read-only Data.\n' >&2
  exit 1
fi

rotated_render="$(mktemp -t xyz-datalab-rotation.XXXXXX)"
trap 'rm -f "${rotated_render}"' EXIT

crossplane render \
  examples/base/001-lab.yaml \
  educates/composition.yaml \
  educates/dependencies/functions.yaml \
  --required-resources educates/tests/environmentconfig.yaml \
  --observed-resources educates/tests/observed/001-rotated-lab.yaml \
  -x \
  >"${rotated_render}"

baseline_checksum="$(awk '/datalabs.pkg.internal\/storage-secret-checksum:/ {print $2; exit}' educates/tests/001x-lab.yaml)"
rotated_checksum="$(awk '/datalabs.pkg.internal\/storage-secret-checksum:/ {print $2; exit}' "${rotated_render}")"

if [[ -z "${baseline_checksum}" || -z "${rotated_checksum}" ]]; then
  printf 'The package-r storage Secret checksum annotation is missing.\n' >&2
  exit 1
fi

if [[ "${baseline_checksum}" == "${rotated_checksum}" ]]; then
  printf 'The package-r storage Secret checksum did not change after token rotation.\n' >&2
  exit 1
fi
