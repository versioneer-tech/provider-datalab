# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

import base64
from collections import Counter
import hashlib
import json
import re
from crossplane.function import request, response
from composition.helpers import (
    _resource_name,
    _to_dict,
    _vcluster_groups,
    _vcluster_role,
    _vcluster_cleanup_generation,
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
    volumes = (xr.get("spec") or {}).get("volumes") or {}
    if any(volume["vcluster"] not in instances for volume in volumes.values()):
        response.fatal(rsp, "Each volume must select a declared virtual cluster.")
        return
    if not instances:
        return
    meta = xr["metadata"]
    name = meta["name"]
    namespace = name
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
    scheduling = config.get("scheduling") or {}
    if not isinstance(scheduling, dict):
        response.fatal(rsp, "vCluster scheduling must be an object.")
        return
    control_scheduling = scheduling.get("controlPlane") or {}
    workload_scheduling = scheduling.get("workloads") or {}
    if not isinstance(control_scheduling, dict) or not isinstance(workload_scheduling, dict):
        response.fatal(rsp, "vCluster controlPlane and workloads scheduling must be objects.")
        return
    if (set(control_scheduling) - {"nodeSelector", "tolerations"}
            or set(workload_scheduling) - {"nodeSelector", "enforceTolerations"}):
        response.fatal(rsp, "Unknown vCluster scheduling field.")
        return
    for section in (control_scheduling, workload_scheduling):
        selector = section.get("nodeSelector") or {}
        if not isinstance(selector, dict) or any(
            not isinstance(k, str) or not isinstance(v, str) for k, v in selector.items()
        ):
            response.fatal(rsp, "vCluster scheduling nodeSelector must map strings to strings.")
            return
    enforced = workload_scheduling.get("enforceTolerations") or []
    if not isinstance(enforced, list) or any(
        not isinstance(t, str) or not re.fullmatch(
            r"[^\s=:]+(?:=[^\s=:]+)?:(?:NoSchedule|PreferNoSchedule|NoExecute)", t
        ) for t in enforced
    ):
        response.fatal(rsp, "vCluster enforceTolerations must use key[=value]:effect strings.")
        return
    tolerations = control_scheduling.get("tolerations") or []
    if not isinstance(tolerations, list) or any(not isinstance(t, dict) for t in tolerations):
        response.fatal(rsp, "vCluster controlPlane tolerations must be Kubernetes toleration objects.")
        return
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
    groups = _vcluster_groups(instance_config)
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
        rsp.desired.resources[key].resource["metadata"]["labels"] = {"datalabs.versioneer.at/vcluster": instance}

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
    workload_egress = [
        rule
        for key in sorted(rsp.desired.resources)
        for policy in [
            _to_dict(rsp.desired.resources[key].resource)
            .get("spec", {})
            .get("forProvider", {})
            .get("manifest", {})
        ]
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
    snapshots = config.get("volumeSnapshots", False)
    if type(snapshots) is not bool:
        response.fatal(rsp, "data.vcluster.volumeSnapshots must be a boolean.")
        return
    configuration["sync"]["fromHost"]["volumeSnapshotClasses"] = {"enabled": snapshots}
    for resource in ("volumeSnapshots", "volumeSnapshotContents"):
        configuration["sync"]["toHost"][resource] = {"enabled": snapshots}
    if snapshots:
        support = _render_template(
            req, "vcluster/snapshot-rbac", namespace=namespace, service_account=service_account,
            snapshot_role=_resource_name(name, instance, "volume-snapshots"),
        )["resources"]
        for suffix, manifest in support.items():
            emit(suffix, manifest)
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
    configuration["controlPlane"]["statefulSet"]["scheduling"].update(control_scheduling)
    configuration["sync"]["fromHost"]["nodes"]["selector"]["labels"].update(
        workload_scheduling.get("nodeSelector") or {}
    )
    configuration["sync"]["toHost"]["pods"]["enforceTolerations"] = enforced
    if workload_scheduling.get("nodeSelector") or enforced:
        policy = _render_template(
            req, "vcluster/placement-policy", namespace=namespace,
            policy_name=_resource_name(namespace, instance, "pod-placement"),
            identity_expression=f"request.userInfo.username == {json.dumps(f'system:serviceaccount:{namespace}:{service_account}')}",
        )
        validations = policy["spec"]["validations"]
        for key, value in sorted((workload_scheduling.get("nodeSelector") or {}).items()):
            validations.append({
                "expression": f"has(object.spec.nodeSelector) && {json.dumps(key)} in object.spec.nodeSelector && object.spec.nodeSelector[{json.dumps(key)}] == {json.dumps(value)}",
                "message": f"Synced Pods must select {key}={value}.",
            })
        for tolerance in enforced:
            pair, effect = tolerance.split(":")
            key, separator, value = pair.partition("=")
            match = f"t.key == {json.dumps(key)} && t.effect == {json.dumps(effect)}"
            match += (f" && (!has(t.operator) || t.operator == 'Equal') && t.value == {json.dumps(value)}"
                      if separator else " && t.operator == 'Exists'")
            if effect == "NoExecute":
                match += " && !has(t.tolerationSeconds)"
            validations.append({
                "expression": f"has(object.spec.tolerations) && object.spec.tolerations.exists(t, {match})",
                "message": f"Synced Pods require toleration {tolerance}.",
            })
        emit("placement-policy", policy)
        emit("placement-policy-binding", _render_template(
            req, "vcluster/storage-policy-binding", namespace=namespace,
            policy_name=policy["metadata"]["name"],
        ))
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
        if suffix == "role" and snapshots:
            manifest["rules"].append({
                "apiGroups": ["snapshot.storage.k8s.io"], "resources": ["volumesnapshots"],
                "verbs": ["create", "delete", "patch", "update", "get", "list", "watch"],
            })
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
    statefulset = _render_template(
        req, "vcluster/statefulset", namespace=namespace,
        configuration_checksum=checksum, resources=resources,
        replicas=0 if instance_config.get("hibernated", False) else 1,
        **template_values,
    )
    statefulset["metadata"]["annotations"] = {
        "datalabs.versioneer.at/lifecycle-request": json.dumps({
            "generation": _vcluster_cleanup_generation(
                req, instance,
                instance_config.get("hibernated", False),
            ),
            "hibernated": bool(instance_config.get("hibernated", False)),
        }, sort_keys=True),
    }
    if control_scheduling:
        statefulset["spec"]["template"]["spec"].update(control_scheduling)
    emit(
        "statefulset",
        statefulset,
        {
            "policy": "DeriveFromCelQuery",
            "celQuery": "has(object.status) && has(object.status.observedGeneration) && object.status.observedGeneration == object.metadata.generation && has(object.status.readyReplicas) && object.status.readyReplicas == object.spec.replicas && has(object.status.currentRevision) && has(object.status.updateRevision) && object.status.currentRevision == object.status.updateRevision",
        },
    )
    if workload_scheduling.get("nodeSelector") or enforced:
        key = _resource_name("vcluster", name, instance, "statefulset")
        dependencies = [_resource_name("vcluster", name, instance, suffix)
                        for suffix in ("placement-policy", "placement-policy-binding")]
        rsp.desired.resources[key].resource["spec"]["references"] = [
            {"dependsOn": {"name": dependency, "namespace": claim_namespace}}
            for dependency in dependencies
        ]
        for dependency in dependencies:
            observed = req.observed.resources.get(dependency)
            body = _to_dict(observed.resource) if observed else {}
            if not any(c.get("type") == "Ready" and c.get("status") == "True"
                       for c in body.get("status", {}).get("conditions", [])):
                rsp.desired.resources[key].resource["spec"]["forProvider"]["manifest"]["spec"]["replicas"] = 0
                break
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

    def virtual(suffix, manifest, preserve=False, readiness=None):
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
        if readiness:
            body["spec"]["readiness"] = readiness
        body["metadata"].setdefault("labels", {})[
            "datalabs.versioneer.at/vcluster"
        ] = instance
        rsp.desired.resources[key].resource.update(body)

    volumes = {
        key: volume
        for key, volume in ((_to_dict(req.observed.composite.resource).get("spec") or {}).get("volumes") or {}).items()
        if volume["vcluster"] == instance
    }
    targets = {"default", *(group["namespace"] for group in groups if group["namespace"] != "*"),
               *(volume.get("namespace", "default") for volume in volumes.values())}
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
    for target in sorted(targets - {"default"}):
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
