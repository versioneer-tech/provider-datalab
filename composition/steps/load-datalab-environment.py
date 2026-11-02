# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

from crossplane.function import request, resource, response
from crossplane.function.proto.v1 import run_function_pb2 as fnv1

from composition.helpers import (
    _to_dict,
)

ENVIRONMENT_KEY = "apiextensions.crossplane.io/environment"


def compose(req: fnv1.RunFunctionRequest, rsp: fnv1.RunFunctionResponse):
    xr = _to_dict(req.observed.composite.resource)
    metadata = xr.get("metadata", {}) or {}
    annotations = metadata.get("annotations", {}) or {}
    labels = metadata.get("labels", {}) or {}
    env_name = (
        annotations.get("datalabs.pkg.internal/environment")
        or labels.get("datalabs.pkg.internal/environment")
        or "datalab"
    ).strip() or "datalab"

    response.require_resources(
        rsp,
        name="datalab-environment",
        api_version="apiextensions.crossplane.io/v1beta1",
        kind="EnvironmentConfig",
        match_name=env_name,
    )

    environment = request.get_required_resource(req, "datalab-environment") or {}
    environment_data = environment.get("data") or {}
    rsp.context.MergeFrom(resource.dict_to_struct({ENVIRONMENT_KEY: environment_data}))
