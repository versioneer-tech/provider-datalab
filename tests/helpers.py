# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

"""Load composition helpers as they run in an embedded function."""

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[1]
BUILDER = runpy.run_path(str(ROOT / "scripts/build-composition.py"))
inline_helpers = BUILDER["inline_helpers"]
HELPER_SOURCE = (ROOT / "composition/helpers.py").read_text()


def load_helpers(*names):
    script = f"from composition.helpers import {', '.join(names)}\n"
    namespace = {}
    # Run the embedded code without a repository module in the function runtime.
    exec(inline_helpers(script, HELPER_SOURCE), namespace)
    return namespace
