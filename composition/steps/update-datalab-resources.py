# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

import hashlib as _hashlib
import ipaddress as _ipaddress
import json as _json
from crossplane.function import response
from composition.helpers import _boolish, _safe_str, _to_dict
from composition.render import _render_template


def _string_list(value):
    return (
        [_safe_str(item) for item in value if _safe_str(item)]
        if isinstance(value, list)
        else []
    )


def compose(req, rsp):
    xr = _to_dict(req.observed.composite.resource)
    meta = xr["metadata"]
    spec = xr.get("spec") or {}
    xr_name = meta["name"]
    xr_namespace = meta.get("namespace") or "default"
    if xr_name == xr_namespace or xr_name == "default" or xr_name.startswith("kube-"):
        response.fatal(
            rsp,
            "The Datalab service namespace must differ from its claim namespace and Kubernetes system namespaces.",
        )
        return
    env = _to_dict(req.context).get(
        "apiextensions.crossplane.io/environment", {}
    )
    defaults = env.get("defaults") or {}
    security = defaults.get("security") or {}
    vcluster = bool(spec.get("vclusters"))
    data_enabled = (defaults.get("data") or {}).get("enabled")
    data_enabled = data_enabled is None or _boolish(data_enabled)
    registry_enabled = _boolish((defaults.get("registry") or {}).get("enabled", True))
    policy = security.get("policy") or "baseline"
    overall_storage = str(
        (defaults.get("overallQuota") or {}).get("storage")
        or "100Gi"
    )
    external_egress = security.get("externalEgress")
    if external_egress is None:
        external_egress = True
    external_egress = _boolish(external_egress)

    network_env = env.get("network") or {}
    excluded_network_policies = set(
        _string_list(network_env.get("excludePolicies") or [])
    )
    blacklist_ips = _string_list(network_env.get("blacklistIPs") or [])
    external_egress_cidrs = _string_list(network_env.get("externalEgressCIDRs") or [])
    internal_egress = network_env.get("internalEgress", [])
    internal_ingress = network_env.get("internalIngress", [])
    internal_cidrs = _string_list(network_env.get("podCIDRs") or [])
    service_cidr = _safe_str(network_env.get("serviceCIDR") or "")
    if service_cidr:
        internal_cidrs.append(service_cidr)

    def _dedupe(items):
        result = []
        for item in items:
            if item not in result:
                result.append(item)
        return result

    external_egress_exceptions = _dedupe(blacklist_ips + internal_cidrs)

    def _policy_enabled(name):
        return name not in excluded_network_policies

    def _network_policy(name, rules, direction="egress", pod_selector=None):
        return _render_template(
            req,
            "datalab-resources/networkpolicy",
            name=name,
            spec={
                "podSelector": pod_selector or {},
                "policyTypes": [direction.capitalize()],
                direction: rules,
            },
        )

    def _cidr_contains(cidr, child):
        try:
            parent = _ipaddress.ip_network(cidr, strict=False)
            candidate = _ipaddress.ip_network(child, strict=False)
        except Exception:
            return False
        return parent.version == candidate.version and candidate.subnet_of(parent)

    def _exceptions_for(cidr):
        return [ip for ip in external_egress_exceptions if _cidr_contains(cidr, ip)]

    def _ip_block(cidr, exceptions):
        block = {"cidr": cidr}
        if exceptions:
            block["except"] = exceptions
        return {"ipBlock": block}

    def _internal_ports(items):
        return [
            {
                key: item[key]
                for key in ("port", "protocol", "endPort")
                if item.get(key) is not None
            }
            for item in items
        ]

    def _internal_rules(items, peer_key):
        field = "internalIngress" if peer_key == "from" else "internalEgress"
        if not isinstance(items, list):
            raise ValueError(f"network.{field} must be a list")
        rules = []
        for item in items:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("namespace"), str)
                or not item["namespace"].strip()
            ):
                raise ValueError(f"network.{field} entries require a namespace")
            selector = item.get("podSelector", {})
            ports = item.get("ports", [])
            if not isinstance(selector, dict):
                raise ValueError(f"network.{field} selectors must be objects")
            if not isinstance(ports, list) or any(
                not isinstance(port, dict) or port.get("port") is None for port in ports
            ):
                raise ValueError(
                    f"network.{field} ports must be a list of port objects"
                )
            peer = {
                "namespaceSelector": {
                    "matchLabels": {
                        "kubernetes.io/metadata.name": item["namespace"].strip(),
                    }
                }
            }
            if selector:
                peer["podSelector"] = selector
            rule = {peer_key: [peer]}
            if ports:
                rule["ports"] = _internal_ports(ports)
            rules.append(rule)
        return rules

    def _add_policy(policies, name, rules, direction="egress"):
        if _policy_enabled(name):
            policies.append(_network_policy(name, rules, direction))

    ingress_policies = {}
    for item, rule in zip(internal_ingress, _internal_rules(internal_ingress, "from")):
        target = item.get("targetPodSelector", {})
        if not isinstance(target, dict):
            raise ValueError("network.internalIngress selectors must be objects")
        name = "allow-internal-ingress"
        if target:
            selector = _json.dumps(target, sort_keys=True, separators=(",", ":"))
            name += "-" + _hashlib.sha256(selector.encode()).hexdigest()[:10]
        ingress_policy = ingress_policies.setdefault(
            name, _network_policy(name, [], "ingress", target)
        )
        if rule not in ingress_policy["spec"]["ingress"]:
            ingress_policy["spec"]["ingress"].append(rule)

    network_policies = []
    _add_policy(network_policies, "deny-ingress", [], "ingress")
    _add_policy(
        network_policies, "allow-namespace-ingress", [{"from": [{"podSelector": {}}]}], "ingress"
    )
    _add_policy(network_policies, "deny-egress", [])
    _add_policy(
        network_policies, "allow-namespace-egress", [{"to": [{"podSelector": {}}]}]
    )

    if external_egress or vcluster or data_enabled or registry_enabled:
        _add_policy(
            network_policies,
            "allow-dns-egress",
            [
                {
                    "to": [
                        {
                            "namespaceSelector": {
                                "matchLabels": {
                                    "kubernetes.io/metadata.name": "kube-system"
                                }
                            }
                        }
                    ],
                    "ports": [
                        {"protocol": "UDP", "port": 53},
                        {"protocol": "TCP", "port": 53},
                    ],
                }
            ],
        )

    if external_egress and external_egress_cidrs:
        _add_policy(
            network_policies,
            "allow-external-egress",
            [
                {"to": [_ip_block(cidr, _exceptions_for(cidr))]}
                for cidr in external_egress_cidrs
            ],
        )

    internal_egress_rules = _internal_rules(internal_egress, "to")
    if internal_egress_rules:
        _add_policy(network_policies, "allow-internal-egress", internal_egress_rules)

    def emit(kind, manifest, suffix=""):
        key = f"{kind.lower()}-{xr_name}{('-' + suffix) if suffix else ''}"
        rsp.desired.resources[key].resource.update(
            _render_template(
                req,
                "common/object",
                key=key,
                xr_namespace=xr_namespace,
                manifest=manifest,
                readiness={"policy": "SuccessfulCreate"},
            )
        )

    emit(
        "Namespace",
        _render_template(
            req,
            "datalab-resources/namespace",
            xr_name=xr_name,
            xr_namespace=xr_namespace,
            policy=policy,
        ),
    )
    emit(
        "ResourceQuota",
        _render_template(
            req,
            "datalab-resources/resourcequota",
            xr_name=xr_name,
            overall_storage=overall_storage,
        ),
        "overall-storage",
    )
    quota_key = f"resourcequota-{xr_name}-overall-storage"
    rsp.desired.resources[quota_key].resource["spec"]["forProvider"]["manifest"]["spec"]["hard"].update(
        {
            "requests.cpu": "4",
            "requests.memory": "8Gi",
            "limits.cpu": "16",
            "limits.memory": "32Gi",
            **((defaults.get("overallQuota") or {}).get("hard") or {}),
        }
    )
    limits = defaults.get("limitRange") or {}
    emit(
        "LimitRange",
        _render_template(
            req,
            "datalab-resources/limitrange",
            xr_name=xr_name,
            default_limits={
                "cpu": "1", "memory": "512Mi", "ephemeral-storage": "8Gi",
                **(limits.get("default") or {}),
            },
            default_requests={
                "cpu": "100m", "memory": "128Mi", "ephemeral-storage": "3Gi",
                **(limits.get("defaultRequest") or {}),
            },
        ),
    )
    policies = network_policies + (
        [policy for name, policy in ingress_policies.items() if _policy_enabled(name)]
        if _policy_enabled("allow-internal-ingress")
        else []
    )
    for manifest in policies:
        manifest["metadata"]["namespace"] = xr_name
        emit("NetworkPolicy", manifest, manifest["metadata"]["name"])
