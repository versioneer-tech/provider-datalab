#!/usr/bin/env bash
set -euo pipefail

if ! command -v kubectl >/dev/null 2>&1; then echo "kubectl not found in PATH" >&2; exit 1; fi
if ! command -v jq >/dev/null 2>&1; then echo "jq not found in PATH" >&2; exit 1; fi

MRAP_NAME=""
GREP_PATTERN=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mrap) MRAP_NAME="${2:-}"; shift 2;;
    --grep) GREP_PATTERN="${2:-}"; shift 2;;
    -h|--help) echo "Usage: $0 [--mrap provider-<name>] [--grep <crd-name-substring>]"; exit 0;;
    *) echo "Unknown argument: $1" >&2; exit 1;;
  esac
done

declare -A CRD_SCOPE_BY_NAME=()
declare -A FQRES_BY_CRD=()
declare -a CRD_LIST=()

CRDS_JSON="$(kubectl get crd -o json)"

if [[ -n "${MRAP_NAME}" ]]; then
  if [[ "${MRAP_NAME}" != provider-* ]]; then echo "Given name '${MRAP_NAME}' is not a provider-* ManagedResourceActivationPolicy" >&2; exit 1; fi
  if ! MRAP_JSON="$(kubectl get managedresourceactivationpolicy "${MRAP_NAME}" -o json 2>/dev/null)"; then
    echo "Cannot read ManagedResourceActivationPolicy '${MRAP_NAME}'" >&2; exit 1
  fi
  mapfile -t ACTIVATES < <(jq -r '.spec.activate[]? // empty' <<<"$MRAP_JSON")
  for entry in "${ACTIVATES[@]}"; do
    resourcePart="${entry%%.*}"
    groupPart="${entry#*.}"
    if [[ "$resourcePart" == "$groupPart" ]]; then continue; fi
    readarray -t MATCHES < <(jq -c --arg grp "$groupPart" --arg r "$resourcePart" '
      .items[]
      | select(.spec.group == $grp)
      | select(
          ((.spec.names.kind // "" | ascii_downcase) == ($r|ascii_downcase)) or
          ((.spec.names.singular // "" | ascii_downcase) == ($r|ascii_downcase)) or
          ((.spec.names.plural // "" | ascii_downcase) == ($r|ascii_downcase))
        )
    ' <<<"$CRDS_JSON")
    for crd in "${MATCHES[@]}"; do
      crdName="$(jq -r '.metadata.name' <<<"$crd")"
      plural="$(jq -r '.spec.names.plural' <<<"$crd")"
      group="$(jq -r '.spec.group' <<<"$crd")"
      scope="$(jq -r '.spec.scope' <<<"$crd")"
      fqres="${plural}.${group}"
      CRD_SCOPE_BY_NAME["$crdName"]="$scope"
      FQRES_BY_CRD["$crdName"]="$fqres"
      CRD_LIST+=( "$crdName" )
    done
  done
fi

if [[ -n "${GREP_PATTERN}" ]]; then
  readarray -t GREP_MATCHES < <(jq -c --arg pat "$GREP_PATTERN" '
    .items[] | select(.metadata.name | test($pat;"i"))
  ' <<<"$CRDS_JSON")
  for crd in "${GREP_MATCHES[@]}"; do
    crdName="$(jq -r '.metadata.name' <<<"$crd")"
    plural="$(jq -r '.spec.names.plural' <<<"$crd")"
    group="$(jq -r '.spec.group' <<<"$crd")"
    scope="$(jq -r '.spec.scope' <<<"$crd")"
    fqres="${plural}.${group}"
    CRD_SCOPE_BY_NAME["$crdName"]="$scope"
    FQRES_BY_CRD["$crdName"]="$fqres"
    CRD_LIST+=( "$crdName" )
  done
fi

if [[ ${#CRD_LIST[@]} -eq 0 ]]; then
  echo "No CRDs discovered. Provide --mrap or --grep (or both)." >&2
  exit 1
fi

mapfile -t CRD_LIST < <(printf "%s\n" "${CRD_LIST[@]}" | sort -u)

for crdName in "${CRD_LIST[@]}"; do
  scope="${CRD_SCOPE_BY_NAME[$crdName]}"
  fqres="${FQRES_BY_CRD[$crdName]}"
  echo "-> ${fqres} (scope: ${scope})"
  if out_json="$(kubectl get "$fqres" -A -o json 2>/dev/null)"; then
    count="$(jq '.items | length' <<<"$out_json")"
    if [[ "$count" -gt 0 ]]; then
      if [[ "$scope" == "Namespaced" ]]; then
        jq -r '.items[] | "\(.metadata.namespace)/\(.metadata.name)"' <<<"$out_json" | awk '{printf "instance: %s\n", $0}'
      else
        jq -r '.items[] | "\(.metadata.name)"' <<<"$out_json" | awk '{printf "instance: %s\n", $0}'
      fi
      if [[ "$scope" == "Namespaced" ]]; then
        jq -r '.items[] | "\(.metadata.namespace) \(.metadata.name)"' <<<"$out_json" \
        | while read -r ns name; do echo "kubectl patch ${fqres} ${name} -n ${ns} --type merge -p '{\"metadata\":{\"finalizers\":[]}}'"; done
        jq -r '.items[] | "\(.metadata.namespace) \(.metadata.name)"' <<<"$out_json" \
        | while read -r ns name; do echo "kubectl delete ${fqres} ${name} -n ${ns} --ignore-not-found"; done
      else
        jq -r '.items[] | "\(.metadata.name)"' <<<"$out_json" \
        | while read -r name; do echo "kubectl patch ${fqres} ${name} --type merge -p '{\"metadata\":{\"finalizers\":[]}}'"; done
        jq -r '.items[] | "\(.metadata.name)"' <<<"$out_json" \
        | while read -r name; do echo "kubectl delete ${fqres} ${name} --ignore-not-found"; done
      fi
    else
      echo "No instances for ${fqres}"
    fi
  else
    echo "No instances for ${fqres}"
  fi
  echo "kubectl patch crd ${crdName} --type merge -p '{\"metadata\":{\"finalizers\":[]}}'"
  echo "kubectl delete crd ${crdName} --ignore-not-found"
  echo
done

PROV_SHORT=""
if [[ -n "${MRAP_NAME}" ]]; then PROV_SHORT="${MRAP_NAME#provider-}"; fi
if [[ -n "${PROV_SHORT}" ]]; then
  if kubectl get deploymentruntimeconfigs.pkg.crossplane.io -o name >/dev/null 2>&1; then
    kubectl get deploymentruntimeconfigs.pkg.crossplane.io -o name | grep -i "$PROV_SHORT" | sed 's#^#kubectl delete #'
    echo
  fi
  if kubectl get providers.pkg.crossplane.io -o name >/dev/null 2>&1; then
    kubectl get providers.pkg.crossplane.io -o name | grep -i "$PROV_SHORT" | sed 's#^#kubectl delete #'
    echo
  fi
  if kubectl get providerrevisions.pkg.crossplane.io -o name >/dev/null 2>&1; then
    kubectl get providerrevisions.pkg.crossplane.io -o name | grep -i "$PROV_SHORT" | sed 's#^#kubectl delete #'
    echo
  fi
  if kubectl get functions.pkg.crossplane.io -o name >/dev/null 2>&1; then
    kubectl get functions.pkg.crossplane.io -o name | grep -i "$PROV_SHORT" | sed 's#^#kubectl delete #'
    echo
  fi
  if kubectl get configurations.pkg.crossplane.io -o name >/dev/null 2>&1; then
    kubectl get configurations.pkg.crossplane.io -o name | grep -i "$PROV_SHORT" | sed 's#^#kubectl delete #'
    echo
  fi
  if kubectl get configurationrevisions.pkg.crossplane.io -o name >/dev/null 2>&1; then
    kubectl get configurationrevisions.pkg.crossplane.io -o name | grep -i "$PROV_SHORT" | sed 's#^#kubectl delete #'
    echo
  fi
  if CRDS_PC="$(kubectl get crd -o json | jq -r '.items[] | select(.spec.names.plural=="providerconfigs") | .metadata.name')" && [[ -n "$CRDS_PC" ]]; then
    while read -r pcCrd; do
      [[ -z "$pcCrd" ]] && continue
      grp="${pcCrd#*.}"
      kindPlural="providerconfigs.${grp}"
      if kubectl get "$kindPlural" -A -o json >/dev/null 2>&1; then
        kubectl get "$kindPlural" -A -o json \
          | jq -r '.items[] | "\((.metadata.namespace // "")) \(.metadata.name)"' \
          | while read -r ns name; do
              if [[ -n "$ns" && "$ns" != " " ]]; then
                echo "kubectl delete ${kindPlural} ${name} -n ${ns}"
              else
                echo "kubectl delete ${kindPlural} ${name}"
              fi
            done
        echo
      fi
    done <<<"$CRDS_PC"
  fi
fi
