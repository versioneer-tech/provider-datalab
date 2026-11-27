#!/usr/bin/env bash
# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

if [[ "${1:-}" == fast ]]; then
  python3 scripts/build-composition.py --check
  exec python3 -m unittest discover -s tests -p 'test_*.py'
fi

examples=(examples/base/00*-lab.yaml)
if (($#)); then
  if (($# != 1)) || [[ ! -f "examples/base/$1-lab.yaml" ]]; then
    printf 'Usage: %s [fast|example number, such as 001]\n' "$0" >&2
    exit 1
  fi
  examples=("examples/base/$1-lab.yaml")
fi

for command_name in crossplane dyff docker python3 go crane; do
  command -v "${command_name}" >/dev/null || { printf 'Missing required command: %s\n' "${command_name}" >&2; exit 1; }
done
docker info >/dev/null
python3 scripts/build-composition.py --check
python3 -m unittest discover -s tests -p 'test_*.py'
python3 tests/environment-schema.py
crossplane_image="$(python3 scripts/components.py --image xpkg.crossplane.io/crossplane/crossplane)"
if (($# == 0)); then
  bash tests/dependencies.bash
fi

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
source = Path('dependencies/functions.yaml').read_text()
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
  local observed=""
  if [[ "${2:-}" == --observed-resources ]]; then
    observed="$3"
  fi
  python3 tests/render.py requirements tests/environmentconfig.yaml "${observed}" "$1" >"${render_dir}/required.yaml"
  crossplane render "$1" composition.yaml "${render_dir}/functions.yaml" \
    --crossplane-image "${crossplane_image}" \
    --crossplane-docker-network "${render_dir##*/}" \
    --required-resources "${render_dir}/required.yaml" -x "${@:2}"
}

started=${SECONDS}
for file in "${examples[@]}"; do
  name="$(basename "${file}")"
  actual="${render_dir}/${name}"
  render "${file}" >"${render_dir}/raw.yaml"
  python3 tests/render.py "${render_dir}/raw.yaml" >"${actual}"
  dyff between "${actual}" "tests/expected/${name}" -s
  observed="tests/observed/${name}"
  if [[ -f "${observed}" ]]; then
    actual="${render_dir}/${name/-lab/x-lab}"
    render "${file}" --observed-resources "${observed}" >"${render_dir}/raw.yaml"
    python3 tests/render.py "${render_dir}/raw.yaml" >"${actual}"
    dyff between "${actual}" "tests/expected/${name/-lab/x-lab}" -s
  fi
done

suites=(vclusters volumes registry s3-connections service-connections oauth2 token-exchange)
if [[ -f "${render_dir}/002x-lab.yaml" ]]; then
  suites+=(backups stores)
fi
if [[ -f "${render_dir}/003x-lab.yaml" ]]; then
  suites+=(settings)
fi
if [[ -f "${render_dir}/001x-lab.yaml" ]]; then
  suites+=(exposure)
fi
python3 - "${render_dir}" "${suites[@]}" <<'PYTHON'
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import subprocess
import sys
import time

work = Path(sys.argv[1])
def run(suite):
    started = time.monotonic()
    result = subprocess.run(["python3", "tests/" + suite + ".py", "--functions", str(work / "functions.yaml"),
                             "--network", work.name], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    return suite, result, time.monotonic() - started

# Containers are already running; each request has its own render input and output.
with ThreadPoolExecutor(max_workers=2) as pool:
    results = []
    for future in as_completed([pool.submit(run, suite) for suite in sys.argv[2:]]):
        suite, result, elapsed = future.result()
        results.append((suite, result, elapsed))
        print(result.stdout, end="", flush=True)
        print(f"{suite}: {elapsed:.1f}s, exit {result.returncode}", flush=True)
if any(result.returncode for _, result, _ in results):
    raise SystemExit(1)
PYTHON
python3 tests/environment-selection.py "${render_dir##*/}-python"
python3 tests/response-ttl.py "${render_dir##*/}-python"

if [[ -f "${render_dir}/001x-lab.yaml" ]]; then
  render examples/base/001-lab.yaml \
    --observed-resources tests/observed/001-rotated-lab.yaml >"${render_dir}/rotated.yaml"
  baseline_checksum="$(awk '/datalabs.versioneer.at\/storage-secret-checksum:/ {print $2; exit}' "${render_dir}/001x-lab.yaml")"
  rotated_checksum="$(awk '/datalabs.versioneer.at\/storage-secret-checksum:/ {print $2; exit}' "${render_dir}/rotated.yaml")"
  if [[ -z "${baseline_checksum}" || -z "${rotated_checksum}" || "${baseline_checksum}" == "${rotated_checksum}" ]]; then
    printf 'The package-r storage Secret checksum did not change after token rotation.\n' >&2
    exit 1
  fi
fi
printf 'Unit checks passed in %s seconds.\n' "$((SECONDS - started))"
