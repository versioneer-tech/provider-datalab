# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

import hashlib as _hashlib
import ipaddress as _ipaddress
import json as _json

from crossplane.function.proto.v1 import run_function_pb2 as fnv1

from composition.helpers import (
    _boolish,
    _extract_manifest,
    _session_name,
    _session_state,
    _string_value,
    _to_dict,
)
from composition.render import _render_template


def _string_list(v):
    if not isinstance(v, list):
        return []
    return [_string_value(item) for item in v if _string_value(item)]


def compose(req: fnv1.RunFunctionRequest, rsp: fnv1.RunFunctionResponse):
    xr = _to_dict(req.observed.composite.resource)
    metadata = xr.get("metadata", {}) or {}
    spec = xr.get("spec", {}) or {}

    xr_name = metadata.get("name")
    xr_namespace = metadata.get("namespace") or "default"

    sessions = [
        _session_name(session, stringify_none=True)
        for session in (spec.get("sessions") or [])
        if _session_name(session, stringify_none=True)
    ]
    started_sessions = [
        _session_name(session, stringify_none=True)
        for session in (spec.get("sessions") or [])
        if _session_name(session, stringify_none=True)
        and _session_state(session) == "started"
    ]
    db_service_names = []
    db_hosts = spec.get("databases") or {}
    if isinstance(db_hosts, dict):
        for host_key in sorted(list(db_hosts.keys())):
            if not isinstance(host_key, str) or not host_key.strip():
                continue
            host_cfg = db_hosts.get(host_key) or {}
            if not isinstance(host_cfg, dict):
                continue
            dbnames = [
                _string_value(x)
                for x in list(host_cfg.get("names") or [])
                if _string_value(x)
            ]
            db_storage = _string_value(host_cfg.get("storage") or "")
            backup_storage = _string_value(host_cfg.get("backupStorage") or "")
            if dbnames and db_storage and backup_storage:
                db_service_names.append(f"{host_key.strip()}-primary")

    context = _to_dict(req.context)
    environment = context.get("apiextensions.crossplane.io/environment", {}) or {}
    defaults = environment.get("defaults") or {}
    vcluster = _boolish((defaults.get("vcluster") or {}).get("enabled", True))
    files = defaults.get("files") or []
    quota = defaults.get("quota") or {}
    overall_quota = defaults.get("overallQuota") or {}

    memory = quota.get("memory") or "2Gi"
    storage = quota.get("storage") or "1Gi"
    budget = quota.get("budget") or "medium"
    overall_storage = _string_value(overall_quota.get("storage") or "100Gi")

    env_security = defaults.get("security") or {}

    policy = env_security.get("policy") or "baseline"

    ka = env_security.get("kubernetesAccess")
    if ka is None:
        ka = True
    kubernetes_access = _boolish(ka)

    role = env_security.get("kubernetesRole") or "edit"

    data_cfg = defaults.get("data") or {}
    data_enabled = data_cfg.get("enabled")
    if data_enabled is None:
        data_enabled = True
    data_enabled = _boolish(data_enabled)

    registry_cfg = defaults.get("registry") or {}
    registry_enabled = registry_cfg.get("enabled")
    if registry_enabled is None:
        registry_enabled = True
    registry_enabled = _boolish(registry_enabled)
    registry_storage = str(registry_cfg.get("storage") or "5Gi")

    persistence_cfg = defaults.get("persistence") or {}
    requested_storage_class = _string_value(
        persistence_cfg.get("storageClassName") or ""
    )

    ingress_env = environment.get("ingress") or {}
    storage_classes_env = environment.get("storageClasses") or {}
    allowed_storage_classes = [
        _string_value(sc)
        for sc in (storage_classes_env.get("allowed") or [])
        if _string_value(sc)
    ]
    packages = environment.get("packages") or []

    ingress_class = ingress_env.get("class", "")
    ingress_domain = ingress_env.get("domain", "default")
    ingress_secret = ingress_env.get("secret", "wildcard-tls")
    permanent_access = _boolish(ingress_env.get("enabled")) or _boolish(
        (environment.get("httpRoute") or {}).get("enabled")
    )

    storage_secret_name = f"{xr_name}-datalab"
    persistent_storage_class = ""
    if allowed_storage_classes:
        persistent_storage_class = (
            requested_storage_class
            if requested_storage_class in allowed_storage_classes
            else allowed_storage_classes[0]
        )
    else:
        persistent_storage_class = requested_storage_class

    external_egress = env_security.get("externalEgress")
    if external_egress is None:
        external_egress = True
    external_egress = _boolish(external_egress)

    network_env = environment.get("network") or {}
    excluded_network_policies = set(
        _string_list(network_env.get("excludePolicies") or [])
    )
    blacklist_ips = _string_list(network_env.get("blacklistIPs") or [])
    external_egress_cidrs = _string_list(network_env.get("externalEgressCIDRs") or [])
    internal_egress = network_env.get("internalEgress", [])
    internal_ingress = network_env.get("internalIngress", [])
    internal_cidrs = _string_list(network_env.get("podCIDRs") or [])
    service_cidr = _string_value(network_env.get("serviceCIDR") or "")
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
            "educates/network-policy",
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

    def _add_policy(policies, name, rules):
        if _policy_enabled(name):
            policies.append(_network_policy(name, rules))

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
    _add_policy(network_policies, "deny-egress", [])
    _add_policy(
        network_policies, "allow-namespace-egress", [{"to": [{"podSelector": {}}]}]
    )

    if vcluster:
        _add_policy(
            network_policies,
            "allow-vcluster-egress",
            [
                {
                    "to": [
                        {
                            "namespaceSelector": {
                                "matchLabels": {
                                    "training.educates.dev/environment.name": xr_name,
                                    "training.educates.dev/session.objects": "true",
                                }
                            },
                            "podSelector": {
                                "matchLabels": {
                                    "app": "vcluster",
                                    "release": "my-vcluster",
                                }
                            },
                        }
                    ],
                    "ports": [
                        {"protocol": "TCP", "port": 443},
                        {"protocol": "TCP", "port": 8443},
                    ],
                }
            ],
        )

    if external_egress or vcluster or data_enabled:
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

    if external_egress:
        if external_egress_cidrs:
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

    vcluster_cfg = {
        "enabled": vcluster,
        "version": "1.34",
        "services": {
            "fromHost": [
                {
                    "from": f"$(workshop_namespace)/{host_svc_name}",
                    "to": f"$(workshop_namespace)/{host_svc_name}",
                }
                for host_svc_name in db_service_names
            ]
        },
    }

    workshop = _render_template(
        req,
        "educates/workshop",
        xr_name=xr_name,
        vcluster_cfg=vcluster_cfg,
        workshop_enabled=bool(files),
        memory=memory,
        storage=storage,
        budget=budget,
        role=role,
        policy=policy,
        kubernetes_access=kubernetes_access,
        storage_secret_name=storage_secret_name,
        files=files,
        packages=packages,
        xr_namespace=xr_namespace,
        network_policies=network_policies,
    )

    if sessions:
        workshop["spec"]["session"]["resources"].pop("storage", None)
        workshop["spec"]["session"]["resources"]["volume"] = {
            "name": "$(session_name)-persistent"
        }

    if data_enabled:
        if permanent_access:
            workshop["spec"]["session"]["dashboards"].append(
                {"name": "Data", "url": f"https://{xr_name}.{ingress_domain}/"}
            )
        else:
            workshop["spec"]["session"]["dashboards"].append(
                {
                    "name": "Data",
                    "url": "$(ingress_protocol)://data-$(session_name).$(ingress_domain)/",
                }
            )
            workshop["spec"]["session"]["ingresses"].append(
                {
                    "name": "data",
                    "authentication": {"type": "session"},
                    "protocol": "http",
                    "host": "package-r.$(workshop_namespace).svc.$(cluster_domain)",
                    "port": 8888,
                    "headers": [{"name": "X-Package-R-User", "value": "datalab"}],
                }
            )

    if policy == "privileged":
        workshop["spec"]["session"]["applications"]["docker"] = {
            "enabled": True,
            "storage": "20Gi",
        }

    if registry_enabled:
        workshop["spec"]["session"]["applications"]["registry"] = {
            "enabled": True,
            "storage": registry_storage,
        }

    if vcluster and service_cidr:
        workshop["spec"]["session"]["objects"].append(
            _render_template(
                req,
                "educates/vcluster-cidr",
                service_cidr=service_cidr,
            )
        )

    environment = _render_template(
        req,
        "educates/workshop-environment",
        xr_name=xr_name,
        ingress_class=ingress_class,
        ingress_domain=ingress_domain,
        ingress_secret=ingress_secret,
    )

    def emit(kind, manifest, key_suffix="", readiness=None):
        suffix = f"-{xr_name}{('-' + key_suffix) if key_suffix else ''}"
        key = f"{kind.lower()}{suffix}"
        body = _render_template(
            req,
            "common/object",
            key=key,
            xr_namespace=xr_namespace,
            manifest=manifest,
            readiness=readiness or {"policy": "SuccessfulCreate"},
        )
        rsp.desired.resources[key].resource.update(body)

    emit("Workshop", workshop)
    emit(
        "WorkshopEnvironment",
        environment,
        readiness={
            "policy": "DeriveFromCelQuery",
            "celQuery": "has(object.status) && has(object.status.educates) && object.status.educates.phase == 'Running'",
        },
    )

    observed_resources = getattr(req.observed, "resources", {}) or {}
    environment_manifest = _extract_manifest(
        observed_resources.get(f"workshopenvironment-{xr_name}")
    )
    workshop_namespace = _string_value(
        ((environment_manifest.get("status") or {}).get("educates") or {}).get(
            "namespace"
        )
        or xr_name
    )

    runtime_namespace = (
        (environment_manifest.get("status") or {}).get("educates") or {}
    ).get("namespace")
    if runtime_namespace and _policy_enabled("allow-internal-ingress"):
        for name, manifest in sorted(ingress_policies.items()):
            if _policy_enabled(name):
                manifest["metadata"]["namespace"] = runtime_namespace
                emit("NetworkPolicy", manifest, key_suffix=name)

    if workshop_namespace:
        emit(
            "ResourceQuota",
            _render_template(
                req,
                "educates/storage-quota",
                workshop_ns=workshop_namespace,
                overall_storage=overall_storage,
            ),
            key_suffix="overall-storage",
        )

        for sid in sessions:
            persistent_pvc_name = f"{xr_name}-{sid}-persistent"
            persistent_pvc_spec = {
                "accessModes": ["ReadWriteOnce"],
                "resources": {"requests": {"storage": storage}},
            }
            if persistent_storage_class:
                persistent_pvc_spec["storageClassName"] = persistent_storage_class
            emit(
                "PersistentVolumeClaim",
                _render_template(
                    req,
                    "educates/workspace-pvc",
                    persistent_pvc_name=persistent_pvc_name,
                    workshop_ns=workshop_namespace,
                    persistent_pvc_spec=persistent_pvc_spec,
                ),
                key_suffix=f"{sid}-persistent",
            )

    for sid in started_sessions:
        session_manifest = _render_template(
            req,
            "educates/session",
            metadata_name=f"{xr_name}-{sid}",
            xr_name=xr_name,
            session_id=str(sid),
            ingress_domain=ingress_domain,
            ingress_secret=ingress_secret,
            session_environment=[
                {"name": "SESSION_NAME", "value": f"{xr_name}-{sid}"},
                {"name": "FRAME_ANCESTORS", "value": ""},
            ]
            + (
                [{"name": "KUBECONFIG", "value": "/opt/kubeconfig/config"}]
                if vcluster
                else []
            ),
        )
        emit(
            "WorkshopSession",
            session_manifest,
            key_suffix=str(sid),
            readiness={
                "policy": "DeriveFromCelQuery",
                "celQuery": "has(object.status) && has(object.status.educates) && object.status.educates.phase == 'Running'",
            },
        )
