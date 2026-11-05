# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

from decimal import Decimal
import re

from crossplane.function.proto.v1 import run_function_pb2 as fnv1
from google.protobuf import json_format, struct_pb2

from composition.helpers import (
    _extract_manifest,
    _runtime_namespace,
    _session_name,
    _session_state,
    _to_dict,
)


def _storage_size(value):
    text = str(value).strip() if value is not None else ""
    match = re.fullmatch(
        r"([+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+))(?:[eE][+-]?[0-9]+|[KMGTPE]i|[numkMGTPE]?)",
        text,
    )
    if not match or Decimal(match[1]) < 0:
        return None
    return text if Decimal(match[1]) else "0"


def compose(req: fnv1.RunFunctionRequest, rsp: fnv1.RunFunctionResponse):
    observed = getattr(req.observed, "resources", None) or {}
    xr = _to_dict(req.observed.composite.resource)
    metadata = xr.get("metadata", {}) or {}
    spec = xr.get("spec", {}) or {}

    xr_name = metadata.get("name")

    sessions = {}
    pvc_namespace = _runtime_namespace(req, xr_name) or xr_name
    counted_volumes = {}
    workshop = rsp.desired.resources.get(f"workshop-{xr_name}")
    workshop = _to_dict(workshop.resource) if workshop else {}
    workshop = workshop.get("spec", {}).get("forProvider", {}).get("manifest") or {}
    workspace = workshop.get("spec", {}).get("session", {}).get("resources")

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

        pvc = rsp.desired.resources.get(f"persistentvolumeclaim-{xr_name}-{sid}-persistent")
        pvc = _to_dict(pvc.resource) if pvc else {}
        pvc = pvc.get("spec", {}).get("forProvider", {}).get("manifest") or {}
        if pvc.get("kind") == "PersistentVolumeClaim":
            size = _storage_size(pvc.get("spec", {}).get("resources", {}).get("requests", {}).get("storage"))
            volume = pvc.get("metadata") or {}
            identity = (volume.get("namespace"), volume.get("name"))
            if all(identity):
                entry["pvcRef"] = {"namespace": identity[0], "name": identity[1]}
                if size is not None:
                    # Assign a shared volume's request to the first listed session.
                    first_session = counted_volumes.setdefault(identity, sid)
                    entry["pvcSize"] = size if first_session == sid else "0"
        elif isinstance(workspace, dict) and not workspace.get("volume"):
            size = _storage_size(workspace["storage"]) if "storage" in workspace else "0"
            if size is not None:
                entry["pvcSize"] = size

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
