# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

from composition.helpers import _boolish, _to_dict
from composition.render import _render_template


def compose(req, rsp):
    environment = (
        _to_dict(req.context).get("apiextensions.crossplane.io/environment") or {}
    )
    data = (environment.get("defaults") or {}).get("data") or {}
    enabled = data.get("enabled")
    registry_enabled = _boolish(((environment.get("defaults") or {}).get("registry") or {}).get("enabled", True))
    if enabled is not None and not _boolish(enabled) and not registry_enabled:
        return
    meta = _to_dict(req.observed.composite.resource)["metadata"]
    name = meta["name"]
    storage = rsp.desired.resources.get(f"connection-{name}-s3")
    if not storage:
        return
    values = {
        key: value
        for key, value in _to_dict(storage.resource).get("stringData", {}).items()
        if key.startswith("AWS_") or key == "aws-credentials"
    }
    key = f"runtime-storage-secret-{name}"
    rsp.desired.resources[key].resource.update(
        _render_template(
            req,
            "common/object",
            key=key,
            xr_namespace=meta.get("namespace") or "default",
            manifest={
                "apiVersion": "v1",
                "kind": "Secret",
                "metadata": {"name": f"{name}-storage", "namespace": name},
                "type": "Opaque",
                "stringData": values,
            },
            readiness={"policy": "SuccessfulCreate"},
        )
    )
