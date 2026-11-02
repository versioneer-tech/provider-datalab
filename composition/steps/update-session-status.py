# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

from crossplane.function.proto.v1 import run_function_pb2 as fnv1
from google.protobuf import json_format, struct_pb2

from composition.helpers import (
    _extract_manifest,
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

    sessions_map = {}

    for session in spec.get("sessions") or []:
        sid = _session_name(session)
        state = _session_state(session)
        if not sid:
            continue

        sessions_map[sid] = {"state": state}

        if state != "started":
            continue

        key = f"workshopsession-{xr_name}-{sid}"
        manifest = _extract_manifest(observed.get(key))
        if not manifest:
            continue

        ws_spec = (manifest.get("spec") or {}).get("session") or {}
        ws_id = str(ws_spec.get("id") or sid)

        educates = (manifest.get("status") or {}).get("educates") or {}
        phase = educates.get("phase")
        url = educates.get("url")
        message = educates.get("message")

        if phase:
            sessions_map[ws_id]["phase"] = phase
        if message:
            sessions_map[ws_id]["message"] = message
        if phase == "Running" and url:
            sessions_map[ws_id]["url"] = url

    cur_status = (xr.get("status") or {}).copy()
    if sessions_map:
        cur_status["sessions"] = sessions_map
    else:
        cur_status.pop("sessions", None)

    status_value = struct_pb2.Value()
    json_format.ParseDict(cur_status, status_value)
    rsp.desired.composite.resource.fields["status"].CopyFrom(status_value)
