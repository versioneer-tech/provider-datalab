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
