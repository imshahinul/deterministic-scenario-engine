from __future__ import annotations

from dataclasses import replace
from datetime import timezone
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
import unittest

from scenario_engine.address import ExecutionAddress
from scenario_engine.clock import LogicalClock
from scenario_engine.dsl import (
    DSLCompilationError,
    DSLSchemaError,
    compile_document,
    parse_yaml,
    run_scenario,
)
from scenario_engine.expressions import ScopeResolutionError
from scenario_engine.runner import ScenarioRunner
from scenario_engine.state import ScenarioState
from scenario_engine.values import MISSING, normalize


EXAMPLE = Path(__file__).parents[1] / "examples" / "phase0_1b_cart.yaml"


def compile_yaml(source: str | None = None):
    return compile_document(parse_yaml(EXAMPLE.read_text() if source is None else source))


def observable(runner: ScenarioRunner):
    return normalize({
        "state": runner.state.to_dict(),
        "history": [{
            "address": record.address.canonical(),
            "timestamp": record.logical_timestamp,
            "pre": record.pre_state_fingerprint,
            "patch": record.state_patch,
            "post": record.post_state_fingerprint,
            "artifacts": record.emitted_artifacts,
            "transition": record.transition_selected,
        } for record in runner.history.records],
        "artifacts": [{
            "type": item.artifact_type,
            "name": item.name,
            "value": item.value,
            "id": item.logical_id,
            "address": item.address.canonical(),
        } for item in runner.artifacts],
        "clock": runner.clock.current,
        "next": runner.next_step,
    })


def fresh_runner(scenario, seed="integration-seed", run_index=0):
    return ScenarioRunner(
        seed,
        ExecutionAddress(scenario.scenario_id, run_index),
        ScenarioState(scenario.initial_state),
        LogicalClock(scenario.reference_clock_start),
    )


class IntegratedPhase01Tests(unittest.TestCase):
    def test_full_declarative_replay_is_exact(self):
        first = run_scenario(compile_yaml(), "replay-seed", 7).normalized()
        second = run_scenario(compile_yaml(EXAMPLE.read_text()), "replay-seed", 7).normalized()
        self.assertEqual(first, second)

    def test_different_run_indexes_are_independently_addressed(self):
        scenario = compile_yaml()
        first = run_scenario(scenario, "address-seed", 3)
        replay = run_scenario(scenario, "address-seed", 3)
        other = run_scenario(scenario, "address-seed", 4)
        self.assertEqual(first.normalized(), replay.normalized())
        self.assertNotEqual(first.runner.address.canonical(), other.runner.address.canonical())
        self.assertNotEqual(first.runner.history.records[0].address.canonical(),
                            other.runner.history.records[0].address.canonical())
        first_ids = [item.logical_id for item in first.runner.artifacts]
        other_ids = [item.logical_id for item in other.runner.artifacts]
        self.assertNotEqual(first_ids, other_ids)

    def test_unrelated_declarative_generator_does_not_shift_existing_values(self):
        source = EXAMPLE.read_text()
        changed = source.replace(
            "      quantity:\n        $int: [1, 4]",
            "      unrelated:\n        $int: [1, 999999]\n"
            "      quantity:\n        $int: [1, 4]",
        )
        before = run_scenario(compile_yaml(source), "isolation-seed", 2).runner
        after = run_scenario(compile_yaml(changed), "isolation-seed", 2).runner
        before_state, after_state = before.state.to_dict(), after.state.to_dict()
        self.assertEqual(before_state["cart_id"], after_state["cart_id"])
        self.assertEqual(before_state["last_item_id"], after_state["last_item_id"])
        self.assertEqual(before_state["cart_items"][0]["quantity"],
                         after_state["cart_items"][0]["quantity"])
        self.assertEqual([item.logical_id for item in before.artifacts],
                         [item.logical_id for item in after.artifacts])

    def test_decimal_and_utc_semantics_survive_yaml_to_runtime(self):
        source = EXAMPLE.read_text().replace(
            '2026-01-01T12:00:00Z', '2026-01-01T07:00:00-05:00'
        )
        scenario = compile_yaml(source)
        result = run_scenario(scenario, "decimal-seed").runner
        state = result.state.to_dict()
        self.assertIsInstance(scenario.initial_state["cart_total"], Decimal)
        self.assertIsInstance(state["cart_total"], Decimal)
        self.assertNotIsInstance(state["cart_total"], float)
        self.assertEqual(state["cart_total"],
                         Decimal("19.99") * state["cart_items"][0]["quantity"])
        self.assertEqual(result.clock.current.isoformat(), "2026-01-01T12:00:06+00:00")
        self.assertEqual(result.clock.current.tzinfo, timezone.utc)
        self.assertTrue(all(record.logical_timestamp.utcoffset() is not None
                            for record in result.history.records))

    def test_missing_and_null_remain_distinct_end_to_end(self):
        source = EXAMPLE.read_text().replace(
            "  cart_total:\n",
            "  missing_value:\n    $missing: true\n  null_value: null\n  cart_total:\n",
            1,
        )
        scenario = compile_yaml(source)
        result = run_scenario(scenario, "missing-seed")
        state = result.runner.state.to_dict()
        self.assertIs(state["missing_value"], MISSING)
        self.assertIsNone(state["null_value"])
        self.assertIs(result.runner.state.snapshot()["missing_value"], MISSING)
        normalized = result.normalized()
        normalized_state = normalized["state"]
        self.assertNotEqual(normalized_state["missing_value"],
                            normalized_state["null_value"])

    def test_derive_dag_order_independence_survives_yaml_compilation(self):
        source = EXAMPLE.read_text()
        start = source.index("    derive:\n", source.index("  - id: add_item"))
        end = source.index("    write:\n", start)
        block = source[start:end]
        split = block.index("      next_cart_total:")
        reordered = "    derive:\n" + (block[split:] + block[len("    derive:\n"):split])
        first = run_scenario(compile_yaml(source), "dag-seed").normalized()
        second = run_scenario(compile_yaml(source[:start] + reordered + source[end:]),
                              "dag-seed").normalized()
        self.assertEqual(first, second)

    def test_failed_derivation_preserves_step_atomicity_through_dsl(self):
        source = EXAMPLE.read_text().replace("$state: cart_items", "$state: absent", 1)
        scenario = compile_yaml(source)
        runner = fresh_runner(scenario)
        runner.run_step(scenario.steps[0].spec)
        before = observable(runner)
        with self.assertRaises(ScopeResolutionError):
            runner.run_step(scenario.steps[1].spec)
        self.assertEqual(before, observable(runner))

    def test_failed_emission_preserves_step_atomicity_through_dsl(self):
        source = EXAMPLE.read_text().replace("$state: last_item_id", "$state: absent", 1)
        scenario = compile_yaml(source)
        runner = fresh_runner(scenario)
        runner.run_step(scenario.steps[0].spec)
        before = observable(runner)
        with self.assertRaises(ScopeResolutionError):
            runner.run_step(scenario.steps[1].spec)
        self.assertEqual(before, observable(runner))

    def test_failed_transition_preserves_step_atomicity_through_dsl(self):
        scenario = compile_yaml()
        runner = fresh_runner(scenario)
        runner.run_step(scenario.steps[0].spec)
        before = observable(runner)

        # Static DSL rules reject bad targets, so mutate only the transition resolver at
        # the closest legitimate compiled/kernel boundary after normal YAML compilation.
        def fail_transition(state):
            raise DSLCompilationError("synthetic transition resolution failure")

        failed_spec = replace(scenario.steps[1].spec, transition=fail_transition)
        with self.assertRaises(DSLCompilationError):
            runner.run_step(failed_spec)
        self.assertEqual(before, observable(runner))

    def test_state_history_artifacts_clock_and_transition_commit_together(self):
        scenario = compile_yaml()
        runner = fresh_runner(scenario)
        before = observable(runner)
        candidate = runner.run_step(scenario.steps[0].spec)
        after = runner.state.to_dict()
        self.assertIsNone(dict(before)["next"])
        self.assertEqual(after["cart_id"], candidate.post_state["cart_id"])
        self.assertEqual(len(runner.history.records), 1)
        self.assertEqual(runner.history.records[0].state_patch["cart_id"], after["cart_id"])
        self.assertEqual(len(runner.artifacts), 1)
        self.assertEqual(runner.artifacts[0].value["cart_id"], after["cart_id"])
        self.assertEqual(runner.clock.current.isoformat(), "2026-01-01T12:00:01+00:00")
        self.assertEqual(runner.next_step, "add_item")
        self.assertEqual(candidate.transition, runner.next_step)

    def test_future_scope_structures_are_rejected_before_execution(self):
        for key in ("resources", "branch", "repeat", "faults", "invariants"):
            with self.subTest(key=key), self.assertRaises(DSLSchemaError):
                parse_yaml(EXAMPLE.read_text() + f"{key}: {{}}\n")

    def test_semantically_equivalent_yaml_key_order_produces_same_result(self):
        source = EXAMPLE.read_text()
        reordered = source.replace(
            "dsl_version: 1\nscenario: cart_checkout\n\nclock:\n  start: \"2026-01-01T12:00:00Z\"\n\ninitial_state:\n"
            "  cart_total:\n    $decimal: \"0.00\"\n  cart_items: []\n  cart_id: null\n"
            "  last_item_id: null\n  checkout_complete: false\n\nsteps:\n",
            "initial_state:\n  checkout_complete: false\n  last_item_id: null\n  cart_id: null\n"
            "  cart_items: []\n  cart_total:\n    $decimal: \"0.00\"\n"
            "clock:\n  start: \"2026-01-01T12:00:00Z\"\nscenario: cart_checkout\n"
            "dsl_version: 1\nsteps:\n",
        ).replace(
            "              item_id:\n                $local: item_id\n"
            "              quantity:\n                $local: quantity\n"
            "              subtotal:\n                $derived: item_subtotal",
            "              subtotal:\n                $derived: item_subtotal\n"
            "              quantity:\n                $local: quantity\n"
            "              item_id:\n                $local: item_id",
        )
        self.assertNotEqual(source, reordered)
        first = run_scenario(compile_yaml(source), "order-seed", 5).normalized()
        second = run_scenario(compile_yaml(reordered), "order-seed", 5).normalized()
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
