# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

from crossplane.function.proto.v1 import run_function_pb2 as fnv1

from composition.helpers import _to_dict


def compose(req, rsp):
    status = _to_dict(req.desired.composite.resource).get("status") or {}
    rsp.desired.composite.ready = req.desired.composite.ready
    if any(connection.get("ready") is not True for connection in status.get("connections", [])):
        rsp.desired.composite.ready = fnv1.READY_FALSE
