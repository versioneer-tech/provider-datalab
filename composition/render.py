# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

import copy as _template_copy
import re as _template_re
from google.protobuf import json_format as _template_json


def _render_template(req, template_name, /, **values):
    """Fill complete scalar placeholders and preserve each value's type."""
    template = _template_json.MessageToDict(req.input["templates"][template_name])

    def fill(value):
        if isinstance(value, str):
            match = _template_re.fullmatch(r"\$\{([A-Za-z_][A-Za-z_0-9]*)\}", value)
            if match:
                return _template_copy.deepcopy(values[match[1]])
        if isinstance(value, dict):
            return {key: fill(item) for key, item in value.items()}
        if isinstance(value, list):
            return [fill(item) for item in value]
        return value

    return fill(template)
