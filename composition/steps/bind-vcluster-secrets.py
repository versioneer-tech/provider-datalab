# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

from collections import Counter
import hashlib
import json
import re

from crossplane.function.proto.v1 import run_function_pb2 as fnv1
from composition.helpers import (
    _extract_manifest,
    _resource_name,
    _secret_data,
    _to_dict,
)
from composition.render import _render_template

OWNER_LABEL = "datalabs.pkg.internal/secret-binding"


def _ready(value):
    body = _to_dict(value.resource) if value else {}
    conditions = body.get("status", {}).get("conditions", [])
    return (
        not body.get("metadata", {}).get("deletionTimestamp")
        and not any(
            item.get("type") == "Synced" and item.get("status") == "False"
            for item in conditions
        )
        and any(
            item.get("type") == "Ready" and item.get("status") == "True"
            for item in conditions
        )
    )


def _approved(export, meta, instance, binding):
    target = binding.get("target") or {}
    keys = binding.get("keys") or {}
    namespace = target.get("namespace", "")
    if not isinstance(export, dict) or not keys:
        return False
    allowed = export.get("keys")
    if not isinstance(allowed, list) or not set(keys) <= set(allowed):
        return False
    if len(set(keys.values())) != len(keys):
        return False
    if (
        not re.fullmatch(r"[a-z]([a-z0-9-]*[a-z0-9])?", namespace)
        or namespace == "default"
        or namespace.startswith("kube-")
    ):
        return False
    identity = {
        "claimNamespace": meta.get("namespace") or "default",
        "datalab": meta["name"],
        "instance": instance,
        "namespace": namespace,
    }
    if identity not in (export.get("targets") or []):
        return False
    return bool(export.get("connection")) != bool(export.get("secretRef"))


def compose(req, rsp):
    xr = _to_dict(req.observed.composite.resource)
    meta = xr["metadata"]
    name = meta["name"]
    claim_namespace = meta.get("namespace") or "default"
    env = _to_dict(req.context).get("apiextensions.crossplane.io/environment") or {}
    exports = env.get("secretExports") or {}
    instances = (xr.get("spec") or {}).get("vclusters") or {}
    statuses = []
    destinations = Counter(
        (instance, binding["target"]["namespace"], binding["target"]["name"])
        for instance, config in instances.items()
        for binding in (config.get("secretBindings") or {}).values()
    )

    def virtual(key, instance, manifest, preserve=False):
        body = _render_template(
            req,
            "vcluster/body",
            key=key,
            claim_namespace=claim_namespace,
            virtual_provider=_resource_name(name, "vcluster", instance),
            manifest=manifest,
        )
        body["metadata"]["labels"] = {"datalabs.pkg.internal/vcluster": instance}
        if preserve:
            body["spec"]["managementPolicies"] = ["Observe", "Create", "Update"]
        rsp.desired.resources[key].resource.update(body)

    def protect(policy_key, target_key):
        for suffix in ("policy", "policy-binding"):
            used = policy_key(suffix)
            key = policy_key("usage-" + suffix)
            reference = lambda item: _render_template(
                req,
                "protect-vcluster-resources/resource",
                apiVersion="kubernetes.m.crossplane.io/v1alpha1",
                kind="Object",
                resourceRef_name=item,
            )
            rsp.desired.resources[key].resource.update(
                _render_template(
                    req,
                    "protect-vcluster-resources/usage",
                    key=key,
                    namespace=claim_namespace,
                    spec_of=reference(used),
                    spec_by=reference(target_key),
                )
            )
            rsp.desired.resources[key].ready = fnv1.READY_TRUE

    for instance, config in sorted(instances.items()):
        for binding_name, binding in sorted(
            (config.get("secretBindings") or {}).items()
        ):
            target = binding["target"]
            status = {
                "name": binding_name,
                "instance": instance,
                "export": binding["export"],
                "target": target,
                "ready": False,
                "reason": "Denied",
            }
            statuses.append(status)
            export = exports.get(binding["export"])
            destination = (instance, target["namespace"], target["name"])
            if (
                not _approved(export, meta, instance, binding)
                or destinations[destination] != 1
            ):
                continue
            owner = hashlib.sha256(
                json.dumps(
                    [
                        claim_namespace,
                        name,
                        meta.get("uid", ""),
                        instance,
                        binding_name,
                        target,
                    ],
                    sort_keys=True,
                ).encode()
            ).hexdigest()[:32]
            key = lambda suffix: _resource_name(
                "vcluster",
                name,
                instance,
                "secret-binding",
                binding_name,
                owner[:10],
                suffix,
            )
            status["reason"] = "SourceNotReady"
            source_ready = False
            if export.get("connection"):
                published = (
                    _to_dict(rsp.desired.composite.resource)
                    .get("status", {})
                    .get("connections", [])
                )
                if not any(
                    item["name"] == export["connection"]
                    and item["type"] in ("s3", "postgres", "mongo", "redis")
                    for item in published
                ):
                    status["reason"] = "Denied"
                    continue
                source_key = f"connection-{name}-{export['connection']}"
                source = rsp.desired.resources.get(source_key)
                data = _secret_data(source)
                source_ready = bool(data) and data == _secret_data(
                    req.observed.resources.get(source_key)
                )
            else:
                source_ref = export["secretRef"]
                if (
                    not isinstance(source_ref, dict)
                    or not source_ref.get("name")
                    or not source_ref.get("namespace")
                ):
                    status["reason"] = "Denied"
                    continue
                observer_key = key(
                    "source-"
                    + hashlib.sha256(
                        json.dumps(source_ref, sort_keys=True).encode()
                    ).hexdigest()[:10]
                )
                rsp.desired.resources[observer_key].resource.update(
                    _render_template(
                        req,
                        "secrets/observer",
                        key=observer_key,
                        xr_namespace=claim_namespace,
                        secret_name=source_ref["name"],
                        secret_namespace=source_ref["namespace"],
                    )
                )
                source = req.observed.resources.get(observer_key)
                manifest = _extract_manifest(source)
                if manifest.get("type") == "kubernetes.io/service-account-token":
                    status["reason"] = "Denied"
                    continue
                data = _secret_data(source)
                source_ready = _ready(source)
            target_key = key("target")
            # Remove an old binding before a new ownership policy reserves the same target.
            replaced = any(
                old_key != target_key
                and _to_dict(old.resource)
                .get("spec", {})
                .get("providerConfigRef", {})
                .get("name")
                == _resource_name(name, "vcluster", instance)
                and old_manifest.get("kind") == "Secret"
                and all(
                    old_manifest.get("metadata", {}).get(field) == target[field]
                    for field in ("name", "namespace")
                )
                and old_manifest.get("metadata", {}).get("labels", {}).get(OWNER_LABEL)
                for old_key, old in req.observed.resources.items()
                for old_manifest in [_extract_manifest(old)]
            )
            if replaced:
                status["reason"] = "ReplacingTarget"
                continue
            previous = req.observed.resources.get(target_key)
            namespace_key = _resource_name(
                "vcluster", name, instance, "access", f"namespace-{target['namespace']}"
            )
            if namespace_key not in rsp.desired.resources:
                virtual(
                    namespace_key,
                    instance,
                    _render_template(
                        req, "vcluster/namespace", target=target["namespace"]
                    ),
                    preserve=True,
                )
            policy_name = _resource_name("datalab", binding_name, owner[:10])
            label_key = json.dumps(OWNER_LABEL)
            check = f"has(value.metadata.labels) && {label_key} in value.metadata.labels && value.metadata.labels[{label_key}] == {json.dumps(owner)}"
            virtual(
                key("policy"),
                instance,
                _render_template(
                    req,
                    "secret-bindings/policy",
                    policy_name=policy_name,
                    target_expression=f"request.namespace == {json.dumps(target['namespace'])} && request.name == {json.dumps(target['name'])}",
                    ownership_expression=f"(oldObject == null || ({check.replace('value.', 'oldObject.')})) && (object == null || ({check.replace('value.', 'object.')}))",
                ),
            )
            virtual(
                key("policy-binding"),
                instance,
                _render_template(
                    req,
                    "secret-bindings/policy-binding",
                    policy_name=policy_name,
                ),
            )
            if not data or not set(binding["keys"]) <= set(data):
                status["reason"] = "MissingSourceKey" if data else "SourceNotReady"
                # Keep the last managed copy during a source outage. Revocation removes the binding.
                if (
                    previous
                    and _extract_manifest(previous)
                    .get("metadata", {})
                    .get("labels", {})
                    .get(OWNER_LABEL)
                    == owner
                ):
                    body = _to_dict(previous.resource)
                    rsp.desired.resources[target_key].resource.update(
                        {
                            "apiVersion": body["apiVersion"],
                            "kind": body["kind"],
                            "metadata": {
                                "name": body["metadata"]["name"],
                                "namespace": claim_namespace,
                                "annotations": {
                                    "crossplane.io/composition-resource-name": target_key
                                },
                                "labels": body["metadata"].get("labels", {}),
                            },
                            "spec": body["spec"],
                        }
                    )
                    protect(key, target_key)
                continue
            if not all(
                _ready(req.observed.resources.get(key(suffix)))
                for suffix in ("policy", "policy-binding")
            ):
                status["reason"] = "ProtectionNotReady"
                continue
            old = _extract_manifest(previous)
            if (
                old
                and old.get("metadata", {}).get("labels", {}).get(OWNER_LABEL) != owner
            ):
                status["reason"] = "TargetConflict"
                virtual(
                    target_key,
                    instance,
                    {
                        "apiVersion": "v1",
                        "kind": "Secret",
                        "metadata": target,
                    },
                )
                rsp.desired.resources[target_key].resource["spec"][
                    "managementPolicies"
                ] = ["Observe"]
                protect(key, target_key)
                continue
            values = {
                target_key_name: data[source_key]
                for source_key, target_key_name in binding["keys"].items()
            }
            virtual(
                target_key,
                instance,
                _render_template(
                    req,
                    "secret-bindings/secret",
                    name=target["name"],
                    namespace=target["namespace"],
                    owner=owner,
                    data=values,
                ),
            )
            protect(key, target_key)
            status["ready"] = (
                source_ready and _ready(previous) and _secret_data(previous) == values
            )
            status["reason"] = (
                "Ready"
                if status["ready"]
                else ("TargetNotReady" if source_ready else "SourceNotReady")
            )
    composite_status = _to_dict(rsp.desired.composite.resource).get("status") or {}
    composite_status["secretBindings"] = statuses
    rsp.desired.composite.resource.update({"status": composite_status})
    rsp.conditions.append(
        fnv1.Condition(
            type="SecretBindingsReady",
            status=fnv1.STATUS_CONDITION_TRUE
            if all(item["ready"] for item in statuses)
            else fnv1.STATUS_CONDITION_FALSE,
            reason="Reconciled"
            if all(item["ready"] for item in statuses)
            else "BindingsPending",
        )
    )
