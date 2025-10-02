#!/usr/bin/env bash
# List instances of CRDs whose group/kind/plural/singular/shortname match a given pattern.
# Usage: ./list-crs.sh <pattern> [<namespace>]
# Requires: kubectl, jq, awk

set -euo pipefail

if ! command -v kubectl >/dev/null 2>&1; then
  echo "kubectl not found in PATH" >&2; exit 1
fi
if ! command -v jq >/dev/null 2>&1; then
  echo "jq not found in PATH" >&2; exit 1
fi

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <pattern> [<namespace>]" >&2
  exit 1
fi

PATTERN="$1"
NS_FILTER="${2:-}"

# Pull all CRDs once
CRDS_JSON="$(kubectl get crd -o json)"

# Use jq to filter by regex across selected name fields (case-insensitive).
# Emit compact JSON objects with the fields we need.
mapfile -t MATCHED < <(
  jq -c --arg re "$PATTERN" '
    .items[]
    | {
        group:      (.spec.group // ""),
        kind:       (.spec.names.kind // ""),
        singular:   (.spec.names.singular // ""),
        plural:     (.spec.names.plural // ""),
        shortNames: (.spec.names.shortNames // []),
        scope:      (.spec.scope // ""),
        fqres:      ((.spec.names.plural // "") + "." + (.spec.group // ""))
      }
    | select(
        (.group      | test($re; "i")) or
        (.kind       | test($re; "i")) or
        (.singular   | test($re; "i")) or
        (.plural     | test($re; "i")) or
        ((.shortNames | join(",")) | test($re; "i"))
      )
  ' <<<"$CRDS_JSON"
)

echo "Matched CRDs for pattern: $PATTERN"
echo

if [[ ${#MATCHED[@]} -eq 0 ]]; then
  echo "No CRDs matched."
  exit 0
fi

for row in "${MATCHED[@]}"; do
  group="$(jq -r '.group' <<<"$row")"
  kind="$(jq -r '.kind' <<<"$row")"
  singular="$(jq -r '.singular' <<<"$row")"
  plural="$(jq -r '.plural' <<<"$row")"
  shortnames="$(jq -r '.shortNames | join(",")' <<<"$row")"
  scope="$(jq -r '.scope' <<<"$row")"
  fqres="$(jq -r '.fqres' <<<"$row")"

  # Guard against malformed rows (shouldn't happen with jq, but keeps it safe under set -u)
  if [[ -z "${fqres}" || -z "${plural}" || -z "${group}" ]]; then
    echo "Skipping malformed CRD row: ${row}"
    echo
    continue
  fi

  echo "CRD: ${fqres}"
  echo "  group:       ${group}"
  echo "  kind:        ${kind}"
  echo "  names:       singular=${singular} plural=${plural} shortNames=[${shortnames}]"
  echo "  scope:       ${scope}"

  if [[ "${scope}" == "Namespaced" ]]; then
    if [[ -n "${NS_FILTER}" ]]; then
      if ! out="$(kubectl get "${fqres}" -n "${NS_FILTER}" -o custom-columns='NAMESPACE:.metadata.namespace,NAME:.metadata.name' --no-headers 2>/dev/null)"; then
        echo "    (kubectl get failed for namespace ${NS_FILTER}; resource may not be served yet or RBAC denies)"
        echo
        continue
      fi
      if [[ -z "${out}" ]]; then
        echo "    No instances found in namespace ${NS_FILTER}."
      else
        awk '{printf "    %s/%s\n", $1, $2}' <<<"${out}"
      fi
    else
      if ! out="$(kubectl get "${fqres}" -A -o custom-columns='NAMESPACE:.metadata.namespace,NAME:.metadata.name' --no-headers 2>/dev/null)"; then
        echo "    (kubectl get failed; resource may not be served yet or RBAC denies)"
        echo
        continue
      fi
      if [[ -z "${out}" ]]; then
        echo "    No instances found."
      else
        awk '{printf "    %s/%s\n", $1, $2}' <<<"${out}"
      fi
    fi
  else
    if ! out="$(kubectl get "${fqres}" -o custom-columns='NAME:.metadata.name' --no-headers 2>/dev/null)"; then
      echo "    (kubectl get failed; resource may not be served yet or RBAC denies)"
      echo
      continue
    fi
    if [[ -z "${out}" ]]; then
      echo "    No instances found."
    else
      awk '{printf "    %s\n", $1}' <<<"${out}"
    fi
  fi

  echo
done
