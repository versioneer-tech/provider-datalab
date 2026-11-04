# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

import base64
from collections import Counter
import hashlib
import json
import re
from crossplane.function import request, response
from composition.helpers import (
    _extract_manifest,
    _resource_name,
    _runtime_namespace,
    _to_dict,
    _vcluster_profile,
    _vcluster_role,
)
from composition.render import _render_template


def _secret_mappings(connections, bindings):
    candidates = []
    for binding in bindings:
        kind, name = binding["type"], binding["name"]
        matches = [
            item for item in connections
            if item["type"] == kind and item["name"] == name
        ]
        if len(matches) != 1 or matches[0].get("ready") is not True:
            continue
        source = matches[0]["secretRef"]
        if not (
            re.fullmatch(r"[a-z0-9]([-a-z0-9]*[a-z0-9])?", source["namespace"])
            and re.fullmatch(r"[a-z0-9]([-a-z0-9.]*[a-z0-9])?", source["name"])
        ):
            continue
        target = binding["target"]
        source_name = f"{source['namespace']}/{source['name']}"
        target_name = f"{target['namespace']}/{target['name']}"
        candidates.append((source_name, target_name))
    sources = Counter(source for source, _ in candidates)
    targets = Counter(target for _, target in candidates)
    return {
        source: target
        for source, target in candidates
        if sources[source] == 1 and targets[target] == 1
    }


def compose(req, rsp):
    xr = _to_dict(req.observed.composite.resource)
    instances = (xr.get("spec") or {}).get("vclusters") or {}
    if not instances:
        return
    meta = xr["metadata"]
    name = meta["name"]
    namespace = _runtime_namespace(req, name)
    if not namespace:
        return
    for instance, instance_config in sorted(instances.items()):
        _compose_instance(
            req,
            rsp,
            name,
            meta.get("namespace") or "default",
            namespace,
            instance,
            instance_config,
        )


def _compose_instance(
    req, rsp, name, claim_namespace, namespace, instance, instance_config
):
    runtime = _resource_name("vcluster", instance, limit=45)
    service_account = f"vc-{runtime}"
    ca_name = f"{runtime}-ca"
    template_values = {
        "runtime": runtime,
        "service_account": service_account,
        "workload_account": f"vc-workload-{runtime}",
        "config_secret": f"vc-config-{runtime}",
        "authentication_name": f"{runtime}-authentication",
        "headless_service": f"{runtime}-headless",
        "data_pvc": f"data-{runtime}-0",
        "ca_name": ca_name,
        "control_policy": f"vc-cp-{runtime}",
        "workload_policy": f"vc-work-{runtime}",
        "dns_policy": f"vc-dns-{runtime}",
        "snapshot_policy": f"vc-snapshot-{runtime}",
        "prefix": f"/.{instance}",
    }
    env = _to_dict(req.context).get("apiextensions.crossplane.io/environment", {}) or {}
    config = env.get("vcluster") or {}
    secret_mappings = _secret_mappings(
        (_to_dict(rsp.desired.composite.resource).get("status") or {}).get("connections") or [],
        instance_config.get("secretBindings") or [],
    )
    iam = env.get("iam") or {}
    route = env.get("httpRoute") or {}
    domain = (env.get("ingress") or {}).get("domain")
    required = {
        "iam.issuerURL": iam.get("issuerURL"),
        "ingress.domain": domain,
        **{
            f"httpRoute.{key}": route.get(key)
            for key in ("parentName", "parentNamespace", "sectionName")
        },
    }
    missing = [key for key, value in required.items() if not str(value or "").strip()]
    if missing:
        response.fatal(
            rsp, "vCluster requires EnvironmentConfig data: " + ", ".join(missing)
        )
        return
    if route.get("enabled") is False:
        response.fatal(
            rsp,
            "vCluster requires EnvironmentConfig data.httpRoute.enabled to be true.",
        )
        return
    issuer = str(iam["issuerURL"]).rstrip("/")
    discovery = str(config.get("discoveryURL") or "").strip()
    if not issuer.startswith("https://") or (
        discovery and (not discovery.startswith("https://"))
    ):
        response.fatal(rsp, "vCluster issuerURL and discoveryURL must use HTTPS.")
        return
    hostname = f"{name}.{domain}"
    backend_hostname = f"{runtime}.{namespace}.svc"
    audience = json.dumps(name)
    groups = sorted(instance_config["groups"], key=lambda item: item["name"])
    roles = [_vcluster_role(instance, group["name"]) for group in groups]
    role_list = json.dumps(roles)
    jwt_issuer = {"url": issuer, "audiences": [name], "audienceMatchPolicy": "MatchAny"}
    if discovery:
        jwt_issuer["discoveryURL"] = discovery
    if config.get("issuerCA"):
        jwt_issuer["certificateAuthority"] = config["issuerCA"]
    authentication = json.dumps(
        _render_template(
            req,
            "vcluster/authenticationconfiguration",
            jwt_issuer=jwt_issuer,
            jwt_0_claimValidationRules_0_expression=f"has(claims.resource_access) && {audience} in claims.resource_access && has(claims.resource_access[{audience}].roles) && claims.resource_access[{audience}].roles.exists(r, r in {role_list})",
            jwt_0_claimMappings_username_prefix=f"datalab:{name}:",
            jwt_0_claimMappings_groups_expression=f"claims.resource_access[{audience}].roles.filter(r, r in {role_list}).map(r, 'datalab:{name}:' + r)",
            **template_values,
        ),
        sort_keys=True,
    )

    def emit(suffix, manifest, readiness=None):
        key = _resource_name("vcluster", name, instance, suffix)
        rsp.desired.resources[key].resource.update(
            _render_template(
                req,
                "common/object",
                key=key,
                xr_namespace=claim_namespace,
                manifest=manifest,
                readiness=readiness or {"policy": "SuccessfulCreate"},
                **template_values,
            )
        )
        rsp.desired.resources[key].resource["metadata"]["labels"] = {"datalabs.pkg.internal/vcluster": instance}

    emit(
        "authentication",
        _render_template(
            req,
            "vcluster/authentication",
            namespace=namespace,
            authentication=authentication,
            **template_values,
        ),
    )
    environment_manifest = (
        _to_dict(rsp.desired.resources[f"workshop-{name}"].resource)
        .get("spec", {})
        .get("forProvider", {})
        .get("manifest", {})
    )
    environment_objects = (
        (environment_manifest.get("spec") or {}).get("environment") or {}
    ).get("objects") or []
    workload_egress = [
        rule
        for policy in environment_objects
        if policy.get("kind") == "NetworkPolicy"
        and policy.get("metadata", {}).get("name")
        in ("allow-external-egress", "allow-internal-egress")
        for rule in policy.get("spec", {}).get("egress", [])
    ]
    storage_config = config.get("storageClasses") or {}
    storage_classes = (
        storage_config.get("allowed") if isinstance(storage_config, dict) else None
    )
    if (
        not isinstance(storage_classes, list)
        or not storage_classes
        or any(
            (not isinstance(item, str) or not item.strip() for item in storage_classes)
        )
        or (len(set(storage_classes)) != len(storage_classes))
    ):
        response.fatal(
            rsp,
            "EnvironmentConfig data.vcluster.storageClasses.allowed must be a non-empty list of unique StorageClass names.",
        )
        return
    default_class = storage_config.get("default") or storage_classes[0]
    storage_class = config.get("storageClassName") or default_class
    if default_class not in storage_classes or storage_class not in storage_classes:
        response.fatal(
            rsp,
            "The vcluster default and control-plane StorageClass must be in data.vcluster.storageClasses.allowed.",
        )
        return
    emit(
        "data",
        _render_template(
            req,
            "vcluster/data",
            namespace=namespace,
            storage_class=storage_class,
            spec_resources_requests_storage=str(
                instance_config.get("storage") or config.get("storage") or "5Gi"
            ),
            **template_values,
        ),
    )
    policy_name = _resource_name(namespace, instance, "storage-classes")
    emit(
        "storage-policy",
        _render_template(
            req,
            "vcluster/storage-policy",
            policy_name=policy_name,
            spec_matchConditions_0_expression=f"request.userInfo.username == {json.dumps(f'system:serviceaccount:{namespace}:{service_account}')}",
            spec_validations_0_expression=f"has(object.spec.storageClassName) && object.spec.storageClassName in {json.dumps(storage_classes)}",
            **template_values,
        ),
    )
    emit(
        "storage-policy-binding",
        _render_template(
            req,
            "vcluster/storage-policy-binding",
            policy_name=policy_name,
            namespace=namespace,
            **template_values,
        ),
    )
    resource_config = config.get("resources") or {}
    resources = {
        "requests": {"cpu": "200m", "memory": "1Gi", "ephemeral-storage": "1Gi"},
        "limits": {"cpu": "4", "memory": "4Gi", "ephemeral-storage": "10Gi"},
    }
    for section in resources:
        resources[section].update(resource_config.get(section) or {})
    configuration = _render_template(
        req,
        "vcluster/configuration",
        namespace=namespace,
        name=_resource_name(name, instance),
        internal_server=f"https://{runtime}.{namespace}:443",
        backend_hostname=backend_hostname,
        storage=str(instance_config.get("storage") or config.get("storage") or "5Gi"),
        storage_class=storage_class,
        resources=resources,
        **template_values,
    )
    embedded = ((config.get("backingStore") or {}).get("database") or {}).get(
        "embedded"
    ) or {}
    configuration["controlPlane"]["backingStore"]["database"]["embedded"].update(
        embedded
    )
    configuration["sync"]["fromHost"]["secrets"] = {
        "enabled": bool(secret_mappings),
        "mappings": {"byName": secret_mappings},
    }
    configuration_json = json.dumps(configuration, sort_keys=True)
    checksum = hashlib.sha256(
        (configuration_json + authentication).encode()
    ).hexdigest()
    emit(
        "config",
        _render_template(
            req,
            "vcluster/config-secret",
            namespace=namespace,
            configuration_data=base64.b64encode(configuration_json.encode()).decode(),
            **template_values,
        ),
    )
    for suffix, manifest in (
        (
            "serviceaccount",
            _render_template(
                req, "vcluster/serviceaccount", namespace=namespace, **template_values
            ),
        ),
        (
            "workload-serviceaccount",
            _render_template(
                req,
                "vcluster/workload-serviceaccount",
                namespace=namespace,
                **template_values,
            ),
        ),
        (
            "role",
            _render_template(
                req, "vcluster/role", namespace=namespace, **template_values
            ),
        ),
        (
            "rolebinding",
            _render_template(
                req, "vcluster/rolebinding", namespace=namespace, **template_values
            ),
        ),
        (
            "service",
            _render_template(
                req, "vcluster/service", namespace=namespace, **template_values
            ),
        ),
        (
            "headless-service",
            _render_template(
                req, "vcluster/headless-service", namespace=namespace, **template_values
            ),
        ),
        (
            "limitrange",
            _render_template(
                req, "vcluster/limitrange", namespace=namespace, **template_values
            ),
        ),
        (
            "control-plane-networkpolicy",
            _render_template(
                req,
                "vcluster/control-plane-networkpolicy",
                namespace=namespace,
                iam_namespace=iam.get("namespace") or "keycloak",
                **template_values,
            ),
        ),
        (
            "dns-networkpolicy",
            _render_template(
                req,
                "vcluster/dns-networkpolicy",
                namespace=namespace,
                **template_values,
            ),
        ),
        (
            "snapshot-networkpolicy",
            _render_template(
                req,
                "vcluster/snapshot-networkpolicy",
                namespace=namespace,
                **template_values,
            ),
        ),
    ):
        emit(suffix, manifest)
    source_namespaces = {key.split("/")[0] for key in secret_mappings} - {namespace}
    for source_namespace in sorted(source_namespaces):
        reader_name = _resource_name(name, instance, "secret-import")
        reader_values = {
            **template_values,
            "namespace": source_namespace,
            "runtime_namespace": namespace,
            "reader_name": reader_name,
        }
        for kind, manifest in (
            ("role", _render_template(req, "vcluster/secret-import-role", **reader_values)),
            ("rolebinding", _render_template(req, "vcluster/secret-import-rolebinding", **reader_values)),
        ):
            emit(
                f"secret-import-{source_namespace}-{kind}",
                manifest,
            )
    workload_policy = _render_template(
        req, "vcluster/workload-networkpolicy", namespace=namespace, **template_values
    )
    workload_policy["spec"]["egress"].extend(workload_egress)
    emit("workload-networkpolicy", workload_policy)
    emit(
        "statefulset",
        _render_template(
            req,
            "vcluster/statefulset",
            namespace=namespace,
            configuration_checksum=checksum,
            resources=resources,
            **template_values,
        ),
        {
            "policy": "DeriveFromCelQuery",
            "celQuery": "has(object.status) && has(object.status.observedGeneration) && object.status.observedGeneration == object.metadata.generation && has(object.status.readyReplicas) && object.status.readyReplicas == object.spec.replicas && has(object.status.currentRevision) && has(object.status.updateRevision) && object.status.currentRevision == object.status.updateRevision",
        },
    )
    virtual_provider = _resource_name(name, "vcluster", instance)
    emit(
        "virtual-providerconfig",
        _render_template(
            req,
            "vcluster/virtual-providerconfig",
            virtual_provider=virtual_provider,
            claim_namespace=claim_namespace,
            namespace=namespace,
            **template_values,
        ),
    )

    def virtual(suffix, manifest, preserve=False):
        key = _resource_name("vcluster", name, instance, "access", suffix)
        body = _render_template(
            req,
            "vcluster/body",
            key=key,
            claim_namespace=claim_namespace,
            virtual_provider=virtual_provider,
            manifest=manifest,
            **template_values,
        )
        if preserve:
            body["spec"]["managementPolicies"] = ["Observe", "Create", "Update"]
        body["metadata"].setdefault("labels", {})[
            "datalabs.pkg.internal/vcluster"
        ] = instance
        rsp.desired.resources[key].resource.update(body)

    for storage_name in storage_classes:
        suffix = hashlib.sha256(storage_name.encode()).hexdigest()[:12]
        emit(
            f"observe-storageclass-{suffix}",
            _render_template(
                req,
                "vcluster/storageclass",
                storage_name=storage_name,
                **template_values,
            ),
        )
        key = _resource_name(
            "vcluster", name, instance, f"observe-storageclass-{suffix}"
        )
        rsp.desired.resources[key].resource["spec"]["managementPolicies"] = ["Observe"]
        observed = req.observed.resources.get(key)
        state = (
            _to_dict(observed.resource).get("status", {}).get("atProvider", {})
            if observed
            else {}
        )
        host_class = state.get("manifest") or state.get("raw", {}).get("manifest") or {}
        if not host_class.get("provisioner"):
            continue
        fields = {
            key: host_class[key]
            for key in (
                "provisioner",
                "parameters",
                "reclaimPolicy",
                "mountOptions",
                "allowVolumeExpansion",
                "volumeBindingMode",
                "allowedTopologies",
            )
            if key in host_class
        }
        virtual(
            f"storageclass-{suffix}",
            {
                **_render_template(
                    req,
                    "vcluster/storageclass-2",
                    storage_name=storage_name,
                    metadata_annotations_storageclass_kubernetes_io_is_default_class=str(
                        storage_name == default_class
                    ).lower(),
                    **template_values,
                ),
                **fields,
            },
        )
    for target in sorted({group["namespace"] for group in groups} - {"*"}):
        virtual(
            f"namespace-{target}",
            _render_template(
                req, "vcluster/namespace", target=target, **template_values
            ),
            preserve=True,
        )
    for group in groups:
        target = group["namespace"]
        role = group["role"]
        suffix = hashlib.sha256(
            f"{group['name']}:{target}:{role}".encode()
        ).hexdigest()[:12]
        manifest = _render_template(
            req,
            "vcluster/manifest",
            kind="ClusterRoleBinding" if target == "*" else "RoleBinding",
            metadata_name=f"datalab-{group['name']}-{role}",
            role=role,
            subjects_0_name=f"datalab:{name}:"
            + _vcluster_role(instance, group["name"]),
            **template_values,
        )
        if target != "*":
            manifest["metadata"]["namespace"] = target
        virtual(f"binding-{suffix}", manifest)
    for group in groups:
        profile = _vcluster_profile(name, instance, group["name"])
        emit(
            f"observe-client-{group['name']}",
            _render_template(
                req,
                "vcluster/secret",
                metadata_name=f"{profile}-oauth",
                claim_namespace=claim_namespace,
                **template_values,
            ),
        )
        rsp.desired.resources[
            _resource_name(
                "vcluster", name, instance, f"observe-client-{group['name']}"
            )
        ].resource["spec"]["managementPolicies"] = ["Observe"]
    response.require_resources(
        rsp,
        name=ca_name,
        api_version="v1",
        kind="Secret",
        match_name=service_account,
        namespace=namespace,
    )
    ca_secret = request.get_required_resource(req, ca_name) or {}
    ca_source = base64.b64decode(ca_secret.get("data", {}).get("config", "")).decode()
    ca_match = re.search("certificate-authority-data:\\s*([A-Za-z0-9+/=]+)", ca_source)
    ca = base64.b64decode(ca_match[1]).decode() if ca_match else ""
    emit(
        "backend-ca",
        _render_template(
            req, "vcluster/backend-ca", namespace=namespace, ca=ca, **template_values
        ),
    )
    parent = {
        "name": route["parentName"],
        "namespace": route["parentNamespace"],
        "sectionName": route["sectionName"],
    }
    emit(
        "backend-tls",
        _render_template(
            req,
            "vcluster/backend-tls",
            apiVersion=(config.get("backendTLS") or {}).get("apiVersion")
            or "gateway.networking.k8s.io/v1",
            namespace=namespace,
            backend_hostname=backend_hostname,
            **template_values,
        ),
        {
            "policy": "DeriveFromCelQuery",
            "celQuery": f"has(object.status) && has(object.status.ancestors) && object.status.ancestors.exists(p, p.ancestorRef.name == {json.dumps(parent['name'])} && has(p.ancestorRef.namespace) && p.ancestorRef.namespace == {json.dumps(parent['namespace'])} && has(p.conditions) && p.conditions.exists(c, c.type == 'Accepted' && c.status == 'True' && c.observedGeneration == object.metadata.generation))",
        },
    )
    emit(
        "route",
        _render_template(
            req,
            "vcluster/route",
            namespace=namespace,
            parent=parent,
            hostname=hostname,
            **template_values,
        ),
        {
            "policy": "DeriveFromCelQuery",
            "celQuery": f"has(object.status) && has(object.status.parents) && object.status.parents.exists(p, p.parentRef.name == {json.dumps(parent['name'])} && has(p.parentRef.namespace) && p.parentRef.namespace == {json.dumps(parent['namespace'])} && has(p.parentRef.sectionName) && p.parentRef.sectionName == {json.dumps(parent['sectionName'])} && has(p.conditions) && p.conditions.exists(c, c.type == 'Accepted' && c.status == 'True' && c.observedGeneration == object.metadata.generation) && p.conditions.exists(c, c.type == 'ResolvedRefs' && c.status == 'True' && c.observedGeneration == object.metadata.generation))",
        },
    )
