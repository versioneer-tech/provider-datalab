#!/usr/bin/env bash
set -euo pipefail

if ! command -v kubectl >/dev/null 2>&1; then
  echo "kubectl not found in PATH" >&2; exit 1
fi
if ! command -v jq >/dev/null 2>&1; then
  echo "jq not found in PATH" >&2; exit 1
fi

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <managedresourceactivationpolicy-name> [<namespace>]" >&2
  exit 1
fi

MRAP_NAME="$1"
MRAP_NS="${2:-}"

KGET=(kubectl get)
if [[ -n "$MRAP_NS" ]]; then
  KGET+=( -n "$MRAP_NS" )
fi

if [[ "$MRAP_NAME" != provider-* ]]; then
  echo "Given name '$MRAP_NAME' is not a provider-* ManagedResourceActivationPolicy"
  exit 1
fi

MRAP_JSON="$("${KGET[@]}" managedresourceactivationpolicy "$MRAP_NAME" -o json)"

mapfile -t ACTIVATES < <(jq -r '.spec.activate[]? // empty' <<<"$MRAP_JSON")

CRDS_JSON="$(kubectl get crd -o json)"

for entry in "${ACTIVATES[@]}"; do
  resourcePart="${entry%%.*}"
  groupPart="${entry#*.}"

  if [[ "$resourcePart" == "$groupPart" ]]; then
    echo
    echo "[$entry] -> Unable to split into <resource>.<group>. Skipping."
    continue
  fi

  readarray -t MATCHES < <(jq -c --arg grp "$groupPart" --arg r "$resourcePart" '
    .items[]
    | select(.spec.group == $grp)
    | select(
        ((.spec.names.kind // "" | ascii_downcase) == ($r|ascii_downcase))
        or ((.spec.names.singular // "" | ascii_downcase) == ($r|ascii_downcase))
        or ((.spec.names.plural // "" | ascii_downcase) == ($r|ascii_downcase))
      )
  ' <<<"$CRDS_JSON")

  echo
  echo "[$entry]"
  if [[ ${#MATCHES[@]} -eq 0 ]]; then
    echo "  No CRD found in group '$groupPart' matching '$resourcePart'."
    continue
  fi

  for crd in "${MATCHES[@]}"; do
    plural="$(jq -r '.spec.names.plural' <<<"$crd")"
    group="$(jq -r '.spec.group' <<<"$crd")"
    scope="$(jq -r '.spec.scope' <<<"$crd")"
    fqres="${plural}.${group}"

    echo "  CRD: ${fqres} (scope: ${scope})"
    if ! out="$(kubectl get "$fqres" -A -o name 2>/dev/null)"; then
      echo "    (kubectl get failed; resource may not be served yet)"
      continue
    fi

    if [[ -z "$out" ]]; then
      echo "    No instances found."
    else
      if [[ "$scope" == "Namespaced" ]]; then
        kubectl get "$fqres" -A -o custom-columns='NAMESPACE:.metadata.namespace,NAME:.metadata.name' --no-headers \
          | awk '{printf "    %s/%s\n", $1, $2}'
      else
        kubectl get "$fqres" -o custom-columns='NAME:.metadata.name' --no-headers \
          | awk '{printf "    %s\n", $1}'
      fi
    fi
  done
done
