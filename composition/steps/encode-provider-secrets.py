# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

import base64
from google.protobuf import json_format


def compose(req, rsp):
    for desired in rsp.desired.resources.values():
        body = json_format.MessageToDict(desired.resource)
        if body.get("kind") != "Object":
            continue
        manifest = body.get("spec", {}).get("forProvider", {}).get("manifest", {})
        if manifest.get("kind") != "Secret" or "stringData" not in manifest:
            continue
        # The provider cannot track write-only stringData through server-side apply.
        manifest.setdefault("data", {}).update(
            {
                key: base64.b64encode(value.encode()).decode()
                for key, value in manifest.pop("stringData").items()
            }
        )
        desired.resource.Clear()
        desired.resource.update(body)
