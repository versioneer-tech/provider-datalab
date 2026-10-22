#!/usr/bin/env bash
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

examples=(examples/base/00*-lab.yaml)
if (($#)); then
  if (($# != 1)) || [[ ! -f "examples/base/$1-lab.yaml" ]]; then
    printf 'Usage: %s [example number, such as 001]\n' "$0" >&2
    exit 1
  fi
  examples=("examples/base/$1-lab.yaml")
fi

for command_name in crossplane dyff docker python3; do
  command -v "${command_name}" >/dev/null || { printf 'Missing required command: %s\n' "${command_name}" >&2; exit 1; }
done
docker info >/dev/null

render_dir="$(mktemp -d /tmp/datalab-render.XXXXXX)"
cleanup() {
  while IFS= read -r name; do
    docker rm -f "${name}" >/dev/null 2>&1 || true
  done <"${render_dir}/containers"
  docker network rm "${render_dir##*/}" >/dev/null 2>&1 || true
  rm -rf "${render_dir}"
}
trap cleanup EXIT

# Reuse one container per function for this run. Product Function objects stay unchanged.
python3 - "${render_dir}" <<'PY'
from pathlib import Path
import re
import sys
work = Path(sys.argv[1])
source = Path('educates/dependencies/functions.yaml').read_text()
names = []
def configure(match):
    name = work.name + '-' + match[1].removeprefix('crossplane-contrib-function-')
    names.append(name)
    return (match[0] + '\n  annotations:\n'
            '    render.crossplane.io/runtime-docker-cleanup: Orphan\n'
            f'    render.crossplane.io/runtime-docker-name: {name}\n'
            f'    render.crossplane.io/runtime-docker-network: {work.name}\n'
            '    render.crossplane.io/runtime-docker-pull-policy: IfNotPresent')
source = re.sub(r'metadata:\n  name: (\S+)', configure, source)
(work / 'functions.yaml').write_text(source)
(work / 'containers').write_text('\n'.join(names) + '\n')
PY
docker network create "${render_dir##*/}" >/dev/null

render() {
  crossplane render "$1" educates/composition.yaml "${render_dir}/functions.yaml" \
    --crossplane-docker-network "${render_dir##*/}" \
    --required-resources educates/tests/environmentconfig.yaml -x "${@:2}"
}

started=${SECONDS}
for file in "${examples[@]}"; do
  name="$(basename "${file}")"
  actual="${render_dir}/${name}"
  render "${file}" >"${actual}"
  dyff between "${actual}" "educates/tests/expected/${name}" -s
  observed="educates/tests/observed/${name}"
  if [[ -f "${observed}" ]]; then
    actual="${render_dir}/${name/-lab/x-lab}"
    render "${file}" --observed-resources "${observed}" >"${actual}"
    dyff between "${actual}" "educates/tests/expected/${name/-lab/x-lab}" -s
  fi
done

if [[ -f "${render_dir}/001x-lab.yaml" ]]; then
  render examples/base/001-lab.yaml \
    --observed-resources educates/tests/observed/001-rotated-lab.yaml >"${render_dir}/rotated.yaml"
  baseline_checksum="$(awk '/datalabs.pkg.internal\/storage-secret-checksum:/ {print $2; exit}' "${render_dir}/001x-lab.yaml")"
  rotated_checksum="$(awk '/datalabs.pkg.internal\/storage-secret-checksum:/ {print $2; exit}' "${render_dir}/rotated.yaml")"
  if [[ -z "${baseline_checksum}" || -z "${rotated_checksum}" || "${baseline_checksum}" == "${rotated_checksum}" ]]; then
    printf 'The package-r storage Secret checksum did not change after token rotation.\n' >&2
    exit 1
  fi
  python3 tests/s3/validate.py --functions "${render_dir}/functions.yaml" --network "${render_dir##*/}"
fi
printf 'Unit checks passed in %s seconds.\n' "$((SECONDS - started))"
