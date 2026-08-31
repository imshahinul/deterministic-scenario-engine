from __future__ import annotations

import copy
import unittest

from scenario_engine.dsl import compile_document, parse_yaml, run_scenario
from scenario_engine.state import ScenarioState
from scenario_engine.values import MISSING, fingerprint, normalize


class MissingSentinelRepairTests(unittest.TestCase):
    def test_missing_singleton_survives_copy_and_deepcopy(self):
        self.assertIs(copy.copy(MISSING), MISSING)
        self.assertIs(copy.deepcopy(MISSING), MISSING)
        self.assertEqual(normalize(MISSING), {"$type": "missing"})

    def test_scenario_state_preserves_missing_identity_through_defensive_copies(self):
        state = ScenarioState({"missing_value": MISSING, "null_value": None})

        snapshot = state.snapshot()
        state_dict = state.to_dict()

        for value in (snapshot["missing_value"], state_dict["missing_value"]):
            self.assertIs(value, MISSING)
        for value in (snapshot["null_value"], state_dict["null_value"]):
            self.assertIsNone(value)
        self.assertEqual(normalize(snapshot["missing_value"]), {"$type": "missing"})
        self.assertEqual(normalize(state_dict["missing_value"]), {"$type": "missing"})
        self.assertIsInstance(state.fingerprint(), str)
        self.assertEqual(state.fingerprint(), fingerprint(state_dict))

    def test_declarative_missing_and_null_survive_end_to_end_runtime_normalization(self):
        source = """
dsl_version: 1
scenario: missing_and_null
clock:
  start: "2026-01-01T00:00:00Z"
initial_state:
  missing_value:
    $missing: true
  null_value: null
steps:
  - id: finish
    transition: null
"""

        document = parse_yaml(source)
        self.assertIs(document.initial_state["missing_value"], MISSING)
        self.assertIsNone(document.initial_state["null_value"])

        scenario = compile_document(document)
        result = run_scenario(scenario, "seed")
        state = result.runner.state.to_dict()

        self.assertIs(state["missing_value"], MISSING)
        self.assertIsNone(state["null_value"])
        self.assertIsNot(state["missing_value"], state["null_value"])
        normalized = result.normalized()
        self.assertEqual(normalized["state"]["missing_value"], {"$type": "missing"})
        self.assertIsNone(normalized["state"]["null_value"])
        self.assertNotEqual(
            normalized["state"]["missing_value"],
            normalized["state"]["null_value"],
        )


if __name__ == "__main__":
    unittest.main()
