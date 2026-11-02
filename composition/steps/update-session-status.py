# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

from crossplane.function.proto.v1 import run_function_pb2 as fnv1
from google.protobuf import json_format as jf
from google.protobuf import struct_pb2 as st


def _to_dict(s):
    return {} if s is None else jf.MessageToDict(s, preserving_proto_field_name=True)


def _extract_manifest(objres):
    if not objres or not getattr(objres, "resource", None):
        return {}
    od = _to_dict(objres.resource)
    atp = (od.get("status") or {}).get("atProvider") or {}
    return (atp.get("manifest") or (atp.get("raw") or {}).get("manifest") or {}) or {}


def _safe_str(v):
    return str(v).strip() if v is not None else ""


def _session_name(session):
    if isinstance(session, dict):
        return _safe_str(session.get("name") or "")
    return _safe_str(session)


def _session_state(session):
    if isinstance(session, dict):
        state = _safe_str(session.get("state") or "started").lower()
    else:
        state = "started"
    if state == "running":
        return "started"
    if state == "paused":
        return "stopped"
    return state


def compose(req: fnv1.RunFunctionRequest, rsp: fnv1.RunFunctionResponse):
    observed = getattr(req.observed, "resources", None) or {}
    xr_obs = _to_dict(req.observed.composite.resource)
    meta = xr_obs.get("metadata", {}) or {}
    spec = xr_obs.get("spec", {}) or {}

    xr_name = meta.get("name")

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

    cur_status = (xr_obs.get("status") or {}).copy()
    if sessions_map:
        cur_status["sessions"] = sessions_map
    else:
        cur_status.pop("sessions", None)

    v = st.Value()
    jf.ParseDict(cur_status, v)
    rsp.desired.composite.resource.fields["status"].CopyFrom(v)
