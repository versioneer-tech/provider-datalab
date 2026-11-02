# Copyright 2026, EOX (https://eox.at) and Versioneer (https://versioneer.at)
# SPDX-License-Identifier: Apache-2.0

import runpy
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
inline_helpers = runpy.run_path(str(ROOT / "scripts/build-composition.py"))[
    "inline_helpers"
]
HELPER_SOURCE = (ROOT / "composition/helpers.py").read_text()


def load_helpers(*names):
    script = f"from composition.helpers import {', '.join(names)}\n"
    namespace = {}
    # Run the embedded code without a repository module in the function runtime.
    exec(inline_helpers(script, HELPER_SOURCE), namespace)
    return namespace


class HelperTests(unittest.TestCase):
    def test_service_tokens_do_not_change(self):
        token = load_helpers("_strong_token")["_strong_token"]
        self.assertEqual(token("xyz:mongo"), "xLKluo0Tk9ElXpQEy1WzmAIY0-nmRBfz")
        self.assertEqual(token("xyz:qdrant:read"), "4om-ip0euXZX1ThMtDimN72Xn7XD7ktF")
        self.assertEqual(
            token("xyz:redis", suffix="", length=28), "q0vhYrvOs2ohHVFyDHjADrEL4WrS"
        )

    def test_session_forms_and_state_aliases(self):
        helpers = load_helpers("_session_name", "_session_state")
        cases = (
            (" xyz ", "xyz", "started"),
            ({"name": " xyz ", "state": " RUNNING "}, "xyz", "started"),
            ({"name": "xyz", "state": "paused"}, "xyz", "stopped"),
            ({"name": "xyz", "state": "stopped"}, "xyz", "stopped"),
            ({"name": "xyz"}, "xyz", "started"),
            (None, "", "started"),
        )
        for session, name, state in cases:
            with self.subTest(session=session):
                self.assertEqual(helpers["_session_name"](session), name)
                self.assertEqual(helpers["_session_state"](session), state)
        self.assertEqual(helpers["_session_name"](None, stringify_none=True), "None")

    def test_null_string_rules_remain_separate(self):
        helpers = load_helpers("_safe_str", "_string_value")
        self.assertEqual(helpers["_safe_str"](None), "")
        self.assertEqual(helpers["_string_value"](None), "None")
        for name in ("_safe_str", "_string_value"):
            self.assertEqual(helpers[name](" xyz "), "xyz")
            self.assertEqual(helpers[name](0), "0")


if __name__ == "__main__":
    unittest.main()
