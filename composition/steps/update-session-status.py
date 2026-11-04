# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

from crossplane.function.proto.v1 import run_function_pb2 as fnv1
from google.protobuf import json_format, struct_pb2

from composition.helpers import (
    _extract_manifest,
    _runtime_namespace,
    _session_name,
    _session_state,
    _to_dict,
)


def compose(req: fnv1.RunFunctionRequest, rsp: fnv1.RunFunctionResponse):
    observed = getattr(req.observed, "resources", None) or {}
    xr = _to_dict(req.observed.composite.resource)
    metadata = xr.get("metadata", {}) or {}
    spec = xr.get("spec", {}) or {}

    xr_name = metadata.get("name")

    sessions = {}
    pvc_namespace = _runtime_namespace(req, xr_name) or xr_name

    for session in spec.get("sessions") or []:
        sid = _session_name(session)
        state = _session_state(session)
        if not sid:
            continue

        entry = {
            "name": sid,
            "state": state,
            "pvcRef": {
                "name": f"{xr_name}-{sid}-persistent",
                "namespace": pvc_namespace,
            },
        }
        sessions[sid] = entry

        if state != "started":
            continue

        key = f"workshopsession-{xr_name}-{sid}"
        manifest = _extract_manifest(observed.get(key))
        if not manifest:
            continue

        educates = (manifest.get("status") or {}).get("educates") or {}
        phase = educates.get("phase")
        url = educates.get("url")
        message = educates.get("message")

        if phase:
            entry["phase"] = phase
        if message:
            entry["message"] = message
        if phase == "Running" and url:
            entry["url"] = url

    cur_status = (xr.get("status") or {}).copy()
    cur_status.update(_to_dict(rsp.desired.composite.resource).get("status") or {})
    cur_status["sessions"] = list(sessions.values())

    status_value = struct_pb2.Value()
    json_format.ParseDict(cur_status, status_value)
    rsp.desired.composite.resource.fields["status"].CopyFrom(status_value)
