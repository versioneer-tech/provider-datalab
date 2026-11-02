# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

from crossplane.function import response
from crossplane.function.proto.v1 import run_function_pb2 as fnv1
from google.protobuf import json_format as _json_format


def _to_dict(struct):
    return (
        {}
        if struct is None
        else _json_format.MessageToDict(struct, preserving_proto_field_name=True)
    )


def _boolish(value):
    if isinstance(value, bool):
        return value
    return str(value).lower() in ("true", "1", "yes", "on")


def _safe_str(value):
    return str(value).strip() if value is not None else ""


def compose(req: fnv1.RunFunctionRequest, rsp: fnv1.RunFunctionResponse):
    context = _to_dict(req.context)
    environment = context.get("apiextensions.crossplane.io/environment", {}) or {}
    data = (environment.get("defaults") or {}).get("data") or {}
    data_enabled = data.get("enabled")
    if data_enabled is None:
        data_enabled = True
    if not _boolish(data_enabled):
        return

    iam = environment.get("iam") or {}
    ingress = environment.get("ingress") or {}
    http_route = environment.get("httpRoute") or {}
    ingress_enabled = _boolish(ingress.get("enabled"))
    route_enabled = _boolish(http_route.get("enabled"))
    s3_enabled = _boolish(http_route.get("enableS3"))
    if ingress_enabled and route_enabled:
        response.fatal(
            rsp,
            "Enable only one of EnvironmentConfig data.ingress.enabled and data.httpRoute.enabled.",
        )
        return
    if s3_enabled and not route_enabled:
        response.fatal(
            rsp,
            "EnvironmentConfig data.httpRoute.enableS3 requires data.httpRoute.enabled.",
        )
        return
    if not (ingress_enabled or route_enabled):
        return

    required = {
        "iam.issuerURL": iam.get("issuerURL"),
        "iam.internalURL": iam.get("internalURL"),
        "ingress.domain": ingress.get("domain"),
    }
    if route_enabled:
        required.update(
            {
                f"httpRoute.{key}": http_route.get(key)
                for key in (
                    "parentName",
                    "parentNamespace",
                    "sectionName",
                    "httpSectionName",
                )
            }
        )
    else:
        required.update(
            {
                "ingress.class": ingress.get("class"),
                "ingress.secret": ingress.get("secret"),
            }
        )
    missing = [name for name, value in required.items() if not _safe_str(value)]
    if missing:
        response.fatal(
            rsp,
            "EnvironmentConfig enables a permanent Data endpoint but is missing: "
            + ", ".join(missing)
            + ".",
        )
