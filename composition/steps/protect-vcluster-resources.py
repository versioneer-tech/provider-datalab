# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

import hashlib
from crossplane.function.proto.v1 import run_function_pb2 as fnv1
from google.protobuf import json_format
from composition.helpers import _resource_name
from composition.render import _render_template


def compose(req, rsp):
    meta = json_format.MessageToDict(req.observed.composite.resource)["metadata"]
    name = meta["name"]
    namespace = meta.get("namespace", "default")
    resources = set(req.observed.resources) | set(rsp.desired.resources)
    objects = {
        key: json_format.MessageToDict(value.resource)
        for key, value in {**req.observed.resources, **rsp.desired.resources}.items()
    }

    def reference(key):
        body = objects[key]
        return _render_template(
            req,
            "protect-vcluster-resources/resource",
            apiVersion=body["apiVersion"],
            kind=body["kind"],
            resourceRef_name=body["metadata"]["name"],
        )

    def protect(suffix, used, by, prefix="vcluster"):
        if used not in resources or by not in resources:
            return
        key = _resource_name(prefix, "usage", suffix, name, used, by)
        rsp.desired.resources[key].resource.update(
            _render_template(
                req,
                "protect-vcluster-resources/usage",
                key=key,
                namespace=namespace,
                spec_of=reference(used),
                spec_by=reference(by),
            )
        )
        rsp.desired.resources[key].ready = fnv1.READY_TRUE

    # Remove a protected resource only after its Usage has cleared the in-use label.
    indexed = {
        (body["apiVersion"], body["kind"], body["metadata"]["name"]): key
        for key, body in objects.items()
    }
    for observed in req.observed.resources.values():
        usage = json_format.MessageToDict(observed.resource)
        if (
            usage.get("kind") != "Usage"
            or usage.get("apiVersion") != "protection.crossplane.io/v1beta1"
        ):
            continue
        target = (usage.get("spec") or {}).get("of") or {}
        key = indexed.get(
            (
                target.get("apiVersion"),
                target.get("kind"),
                (target.get("resourceRef") or {}).get("name"),
            )
        )
        if key is None or key in rsp.desired.resources:
            continue
        body = objects[key]
        metadata = body["metadata"]
        rsp.desired.resources[key].resource.update(
            _render_template(
                req,
                "protect-vcluster-resources/resource-2",
                apiVersion=body["apiVersion"],
                kind=body["kind"],
                metadata_name=metadata["name"],
                namespace=namespace,
                key=key,
                spec=body.get("spec") or {},
            )
        )

        if metadata.get("labels"):
            rsp.desired.resources[key].resource["metadata"]["labels"] = metadata[
                "labels"
            ]

    for instance in sorted(
        {
            body.get("metadata", {})
            .get("labels", {})
            .get("datalabs.pkg.internal/vcluster")
            for body in objects.values()
        }
        - {None}
    ):
        control_plane = _resource_name("vcluster", name, instance, "statefulset")
        protect(
            f"{instance}-quota", f"resourcequota-{name}-overall-storage", control_plane
        )
        for suffix in (
            "authentication",
            "config",
            "data",
            "serviceaccount",
            "workload-serviceaccount",
            "role",
            "rolebinding",
            "service",
            "headless-service",
            "limitrange",
            "storage-policy",
            "storage-policy-binding",
            "control-plane-networkpolicy",
            "workload-networkpolicy",
            "dns-networkpolicy",
            "snapshot-networkpolicy",
        ):
            protect(
                f"{instance}-{suffix}",
                _resource_name("vcluster", name, instance, suffix),
                control_plane,
            )
        for key, body in objects.items():
            if body.get("metadata", {}).get("labels", {}).get(
                "datalabs.pkg.internal/vcluster"
            ) == instance and body.get("spec", {}).get("providerConfigRef", {}).get(
                "name"
            ) == _resource_name(
                name, "vcluster", instance
            ):
                suffix = hashlib.sha256(key.encode()).hexdigest()[:12]
                protect(f"{instance}-control-{suffix}", control_plane, key)
                protect(
                    f"{instance}-provider-{suffix}",
                    _resource_name(
                        "vcluster", name, instance, "virtual-providerconfig"
                    ),
                    key,
                )

    identity_refs = {
        "clientId": ("openidclient.keycloak.m.crossplane.io/v1alpha1", "Client"),
        "serviceAccountUserClientId": (
            "openidclient.keycloak.m.crossplane.io/v1alpha1",
            "Client",
        ),
        "roleId": ("role.keycloak.m.crossplane.io/v1alpha1", "Role"),
        "role": ("role.keycloak.m.crossplane.io/v1alpha1", "Role"),
        "groupId": ("group.keycloak.m.crossplane.io/v1alpha1", "Group"),
    }
    for key, body in objects.items():
        if ".keycloak.m.crossplane.io/" in body.get("apiVersion", ""):
            params = body.get("spec", {}).get("forProvider", {})
            for field, (api_version, kind) in identity_refs.items():
                refs = [params.get(field + "Ref", {})]
                if field == "roleId":
                    refs.extend(params.get("roleIdsRefs") or [])
                labels = (params.get(field + "Selector") or {}).get("matchLabels")
                for parent, candidate in objects.items():
                    if (
                        candidate.get("apiVersion") != api_version
                        or candidate.get("kind") != kind
                    ):
                        continue
                    metadata = candidate.get("metadata", {})
                    if not any(
                        ref.get("name") == metadata.get("name") for ref in refs
                    ) and not (
                        labels
                        and all(
                            metadata.get("labels", {}).get(k) == v
                            for k, v in labels.items()
                        )
                    ):
                        continue
                    suffix = hashlib.sha256(f"{parent}:{key}".encode()).hexdigest()[:12]
                    protect(suffix, parent, key, prefix="keycloak")
        if body.get("kind") != "Object":
            continue
        manifest = body.get("spec", {}).get("forProvider", {}).get("manifest", {})
        if manifest.get("metadata", {}).get("namespace") == name:
            suffix = hashlib.sha256(key.encode()).hexdigest()[:12]
            protect(suffix, f"namespace-{name}", key, prefix="datalab")
