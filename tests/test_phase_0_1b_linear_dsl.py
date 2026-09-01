from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import unittest

from scenario_engine.clock import LogicalClock
from scenario_engine.dsl import (
    DSLCompilationError, DSLParseError, DSLSchemaError,
    UnsupportedDSLVersionError, compile_document, decode_semantic_value,
    parse_yaml, parse_yaml_file, run_scenario,
)
from scenario_engine.expressions import ScopeResolutionError
from scenario_engine.runner import ScenarioRunner
from scenario_engine.address import ExecutionAddress
from scenario_engine.state import ScenarioState
from scenario_engine.values import MISSING, normalize


ROOT = Path(__file__).parents[1]
EXAMPLE = ROOT / "examples" / "phase0_1b_cart.yaml"


def compiled_example(text: str | None = None):
    return compile_document(parse_yaml(text if text is not None else EXAMPLE.read_text()))


class LinearDSLTests(unittest.TestCase):
    def test_parse_and_run_linear_yaml_scenario(self):
        scenario = compile_document(parse_yaml_file(EXAMPLE))
        result = run_scenario(scenario, "seed", 7)
        state = result.runner.state.to_dict()
        self.assertIsInstance(state["cart_total"], Decimal)
        quantity = state["cart_items"][0]["quantity"]
        self.assertEqual(state["cart_total"], Decimal("19.99") * quantity)
        self.assertEqual(state["last_item_id"], state["cart_items"][0]["item_id"])
        self.assertEqual(len(result.runner.history.records), 3)
        self.assertEqual([item.artifact_type for item in result.runner.artifacts],
                         ["cart_created", "cart_item_added", "cart_checked_out"])
        self.assertEqual(result.runner.artifacts[1].value["cart_total"], state["cart_total"])
        self.assertEqual(result.runner.clock.current.isoformat(), "2026-01-01T12:00:06+00:00")
        self.assertIsNone(result.runner.next_step)

    def test_same_yaml_same_context_replays_exactly(self):
        scenario = compiled_example()
        self.assertEqual(run_scenario(scenario, "seed", 4).normalized(),
                         run_scenario(scenario, "seed", 4).normalized())

    def test_unrelated_generator_does_not_shift_existing_outputs(self):
        source = EXAMPLE.read_text()
        changed = source.replace("      quantity:\n        $int: [1, 4]", "      unrelated:\n        $int: [1, 999999]\n      quantity:\n        $int: [1, 4]")
        before = run_scenario(compiled_example(source), "seed", 2).runner.state.to_dict()
        after = run_scenario(compiled_example(changed), "seed", 2).runner.state.to_dict()
        self.assertEqual(before, after)

    def test_yaml_float_is_rejected(self):
        source = EXAMPLE.read_text().replace('$decimal: "19.99"', "$literal: 19.99", 1)
        with self.assertRaises(DSLSchemaError):
            parse_yaml(source)

    def test_non_v1_dsl_version_is_rejected(self):
        with self.assertRaises(UnsupportedDSLVersionError):
            parse_yaml(EXAMPLE.read_text().replace("dsl_version: 1", "dsl_version: 2"))

    def test_unknown_keys_are_rejected(self):
        with self.assertRaisesRegex(DSLSchemaError, "unknown key"):
            parse_yaml(EXAMPLE.read_text() + "unknown: true\n")

    def test_duplicate_step_ids_are_rejected(self):
        source = EXAMPLE.read_text().replace("  - id: add_item", "  - id: create_cart")
        with self.assertRaisesRegex(DSLSchemaError, "duplicate step ID"):
            parse_yaml(source)

    def test_non_linear_transition_is_rejected(self):
        source = EXAMPLE.read_text().replace("transition: add_item", "transition: checkout", 1)
        with self.assertRaises(DSLCompilationError):
            compiled_example(source)

    def test_final_transition_must_be_null(self):
        source = EXAMPLE.read_text().replace("    transition: null", "    transition: create_cart")
        with self.assertRaisesRegex(DSLCompilationError, "final step transition must be null"):
            compiled_example(source)

    def test_later_scope_constructs_are_rejected(self):
        for key in ("inputs", "resources", "branch", "branches", "repeat", "subflow",
                    "subflows", "faults", "invariants", "constraints"):
            with self.subTest(key=key), self.assertRaises(DSLSchemaError):
                parse_yaml(EXAMPLE.read_text() + f"{key}: {{}}\n")

    def test_emit_references_post_state_only(self):
        result = run_scenario(compiled_example(), "seed").runner
        self.assertEqual(result.artifacts[0].value["cart_id"], result.state.to_dict()["cart_id"])
        bad = EXAMPLE.read_text().replace("$state: last_item_id", "$local: item_id")
        with self.assertRaisesRegex(DSLSchemaError, "not allowed in emission"):
            parse_yaml(bad)

    def test_custom_yaml_tags_are_rejected(self):
        with self.assertRaises(DSLParseError):
            parse_yaml("dsl_version: !!python/object/apply:builtins.str [1]\n")

    def test_clock_must_be_timezone_aware(self):
        source = EXAMPLE.read_text().replace("2026-01-01T12:00:00Z", "2026-01-01T12:00:00")
        with self.assertRaisesRegex(DSLSchemaError, "timezone-aware"):
            parse_yaml(source)

    def test_derive_key_order_is_semantically_irrelevant(self):
        source = EXAMPLE.read_text()
        start = source.index("    derive:\n", source.index("  - id: add_item"))
        end = source.index("    write:\n", start)
        block = source[start:end]
        reordered = block[block.index("      next_cart_total:"):] + block[:block.index("      next_cart_total:")]
        reordered = "    derive:\n" + reordered.replace("    derive:\n", "")
        first = run_scenario(compiled_example(source), "seed").normalized()
        second = run_scenario(compiled_example(source[:start] + reordered + source[end:]), "seed").normalized()
        self.assertEqual(first, second)

    def test_missing_is_distinct_from_null_in_dsl_values(self):
        self.assertNotEqual(normalize(decode_semantic_value({"$missing": True})), normalize(None))
        self.assertIs(decode_semantic_value({"$missing": True}), MISSING)

    def test_failed_declarative_step_preserves_kernel_atomicity(self):
        source = EXAMPLE.read_text().replace("$state: cart_items", "$state: absent", 1)
        scenario = compiled_example(source)
        runner = ScenarioRunner("seed", ExecutionAddress(scenario.scenario_id),
                                ScenarioState(scenario.initial_state),
                                LogicalClock(scenario.reference_clock_start))
        runner.run_step(scenario.steps[0].spec)
        before = normalize({"state": runner.state.to_dict(), "clock": runner.clock.current,
                            "history": len(runner.history.records), "artifacts": len(runner.artifacts),
                            "next": runner.next_step})
        with self.assertRaises(ScopeResolutionError):
            runner.run_step(scenario.steps[1].spec)
        after = normalize({"state": runner.state.to_dict(), "clock": runner.clock.current,
                           "history": len(runner.history.records), "artifacts": len(runner.artifacts),
                           "next": runner.next_step})
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
