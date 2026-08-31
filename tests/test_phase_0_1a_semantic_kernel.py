from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import ast
from pathlib import Path
import unittest

from scenario_engine.address import ExecutionAddress
from scenario_engine.artifacts import GeneratedArtifact
from scenario_engine.clock import LogicalClock
from scenario_engine.context import GenerationContext
from scenario_engine.expressions import (
    Add, Append, DerivedRef, DerivationCycleError, EvaluationEnvironment,
    Expression, Literal, LocalRef, Multiply, Record, StateRef, SumField,
    resolve_derivations,
)
from scenario_engine.ids import DeterministicIDProvider
from scenario_engine.rng import DeterministicRNG, IntegerRange
from scenario_engine.runner import ScenarioRunner, StepSpec
from scenario_engine.state import ScenarioState
from scenario_engine.values import MISSING, canonical_bytes, fingerprint, normalize


REFERENCE = datetime(2030, 1, 2, 12, 0, tzinfo=timezone(timedelta(hours=2)))


class Boom(Expression):
    def evaluate(self, env: EvaluationEnvironment):
        raise RuntimeError("deliberate failure")


def add_item_spec(order: tuple[str, ...] = ("subtotal", "items", "total")) -> StepSpec:
    definitions = {
        "subtotal": Multiply(Literal(Decimal("19.99")), LocalRef("quantity")),
        "items": Append(StateRef("cart_items"), Record({
            "quantity": LocalRef("quantity"), "subtotal": DerivedRef("subtotal")
        })),
        "total": SumField(DerivedRef("items"), "subtotal"),
    }
    derivations = {name: definitions[name] for name in order}

    def emit(context, post_state, locals_, derived):
        address = context.address.child("emit", "cart_item_added")
        return (GeneratedArtifact(
            "cart_item_added", "cart_item_added",
            {"cart_total": post_state["cart_total"], "quantity": locals_["quantity"]},
            context.ids.derive(address, "artifact"), address,
        ),)

    return StepSpec(
        "add_item", {"quantity": IntegerRange(3, 3)}, derivations,
        {"cart_items": DerivedRef("items"), "cart_total": DerivedRef("total")},
        timedelta(minutes=5), lambda state: None, emit, lambda state: "checkout",
    )


def runner(seed="seed", run_index=0):
    return ScenarioRunner(
        seed, ExecutionAddress("checkout", run_index),
        ScenarioState({"cart_items": [], "cart_total": Decimal("0.00")}),
        LogicalClock(REFERENCE),
    )


def observable(subject: ScenarioRunner):
    return normalize({
        "state": subject.state.to_dict(),
        "history": [{
            "address": record.address.canonical(),
            "timestamp": record.logical_timestamp,
            "pre": record.pre_state_fingerprint,
            "patch": record.state_patch,
            "post": record.post_state_fingerprint,
            "artifacts": [[str(item_id), kind] for item_id, kind in record.emitted_artifacts],
            "transition": record.transition_selected,
        } for record in subject.history.records],
        "artifacts": [{
            "type": item.artifact_type, "name": item.name, "value": item.value,
            "id": item.logical_id, "address": item.address.canonical(),
        } for item in subject.artifacts],
        "clock": subject.clock.current,
        "next": subject.next_step,
    })


class SemanticKernelTests(unittest.TestCase):
    def test_same_context_replay(self):
        first, second = runner(), runner()
        first.run_step(add_item_spec())
        second.run_step(add_item_spec(("total", "items", "subtotal")))
        self.assertEqual(observable(first), observable(second))

    def test_address_isolation(self):
        base = ExecutionAddress("s").for_step("step")
        before = {name: DeterministicRNG("seed", base.child("generate", name)).inclusive_int(1, 10**9)
                  for name in ("a", "b")}
        after = {name: DeterministicRNG("seed", base.child("generate", name)).inclusive_int(1, 10**9)
                 for name in ("c", "a", "b")}
        self.assertEqual(before, {key: after[key] for key in before})

    def test_future_repetition_addressing(self):
        base = ExecutionAddress("s").for_step("x")
        zero, one = base.with_repetition(0), base.with_repetition(1)
        rng0, rng1 = DeterministicRNG("seed", zero), DeterministicRNG("seed", one)
        self.assertEqual(rng0.inclusive_int(1, 100), DeterministicRNG("seed", zero).inclusive_int(1, 100))
        self.assertNotEqual(rng0.derivation_material("inclusive-int"), rng1.derivation_material("inclusive-int"))
        ids = DeterministicIDProvider("seed")
        self.assertNotEqual(ids.derivation_material(zero, "x"), ids.derivation_material(one, "x"))

    def test_deterministic_ids(self):
        ids, address = DeterministicIDProvider("seed"), ExecutionAddress("s")
        self.assertEqual(ids.derive(address, "one"), ids.derive(address, "one"))
        self.assertNotEqual(ids.derive(address, "one"), ids.derive(address, "two"))
        self.assertNotEqual(ids.derive(address, "one"), ids.derive(address.child("x"), "one"))

    def test_decimal_money_and_value_types(self):
        self.assertEqual(Decimal("19.99") * 3, Decimal("59.97"))
        self.assertNotEqual(normalize(MISSING), normalize(None))
        with self.assertRaises(ValueError):
            normalize(datetime(2030, 1, 1))

    def test_clock_determinism_and_failed_step_does_not_advance(self):
        subject = runner()
        expected = REFERENCE.astimezone(timezone.utc)
        self.assertEqual(subject.clock.current, expected)
        bad = StepSpec("bad", {}, {"x": Boom()}, {}, timedelta(days=1))
        with self.assertRaises(RuntimeError):
            subject.run_step(bad)
        self.assertEqual(subject.clock.current, expected)

    def test_derive_dag_order_independence(self):
        first, second = runner(), runner()
        first.run_step(add_item_spec(("subtotal", "items", "total")))
        second.run_step(add_item_spec(("total", "subtotal", "items")))
        self.assertEqual(first.state.to_dict(), second.state.to_dict())

    def test_derive_cycle_rejected_before_mutation(self):
        subject = runner()
        spec = StepSpec("cycle", {}, {"a": DerivedRef("b"), "b": DerivedRef("a")}, {})
        before = observable(subject)
        with self.assertRaisesRegex(DerivationCycleError, "a, b"):
            subject.run_step(spec)
        self.assertEqual(observable(subject), before)

    def assert_atomic_failure(self, spec: StepSpec, error=RuntimeError):
        subject, before = runner(), None
        before = observable(subject)
        with self.assertRaises(error):
            subject.run_step(spec)
        self.assertEqual(observable(subject), before)

    def test_failed_derivation_atomicity(self):
        self.assert_atomic_failure(StepSpec("bad", {}, {"x": Boom()}, {"cart_total": Literal(Decimal("1"))}, timedelta(hours=1)))

    def test_failed_emission_atomicity(self):
        def fail(*args):
            raise RuntimeError("emission failed")
        self.assert_atomic_failure(StepSpec("bad", {}, {}, {"cart_total": Literal(Decimal("1"))}, timedelta(hours=1), emit=fail))

    def test_failed_transition_atomicity(self):
        def fail(state):
            raise RuntimeError("transition failed")
        self.assert_atomic_failure(StepSpec("bad", {}, {}, {"cart_total": Literal(Decimal("1"))}, timedelta(hours=1), transition=fail))

    def test_failed_history_construction_atomicity(self):
        def fail(**kwargs):
            raise RuntimeError("history failed")
        self.assert_atomic_failure(StepSpec("bad", {}, {}, {"cart_total": Literal(Decimal("1"))}, timedelta(hours=1), history_builder=fail))

    def test_successful_whole_step_commit(self):
        subject = runner()
        subject.run_step(add_item_spec())
        self.assertEqual(subject.state.to_dict()["cart_total"], Decimal("59.97"))
        self.assertEqual(len(subject.history.records), 1)
        self.assertEqual(len(subject.artifacts), 1)
        self.assertEqual(subject.clock.current, REFERENCE.astimezone(timezone.utc) + timedelta(minutes=5))
        self.assertEqual(subject.next_step, "checkout")
        self.assertEqual(subject.artifacts[0].value["cart_total"], Decimal("59.97"))

    def test_canonical_map_semantics(self):
        left, right = {"b": [2, 1], "a": Decimal("1.20")}, {"a": Decimal("1.20"), "b": [2, 1]}
        self.assertEqual(normalize(left), normalize(right))
        self.assertEqual(canonical_bytes(left), canonical_bytes(right))
        self.assertEqual(fingerprint(left), fingerprint(right))

    def test_different_run_index_addressing(self):
        zero, one = ExecutionAddress("s", 0), ExecutionAddress("s", 1)
        self.assertNotEqual(zero.canonical(), one.canonical())
        rng0, rng1 = DeterministicRNG("seed", zero), DeterministicRNG("seed", one)
        self.assertNotEqual(rng0.derivation_material("inclusive-int"), rng1.derivation_material("inclusive-int"))
        self.assertEqual(rng0.inclusive_int(1, 100), DeterministicRNG("seed", zero).inclusive_int(1, 100))

    def test_nondeterminism_escape_hatch_guard(self):
        source_root = Path(__file__).parents[1] / "src" / "scenario_engine"
        forbidden_calls = {("uuid", "uuid4"), ("datetime", "now"), ("datetime", "utcnow"),
                           ("time", "time"), ("secrets", "token_bytes"), ("random", "SystemRandom")}
        for path in source_root.glob("*.py"):
            tree = ast.parse(path.read_text())
            imports_random = False
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    names = [alias.name for alias in node.names]
                    imports_random |= node.module == "random" if isinstance(node, ast.ImportFrom) else "random" in names
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                    self.assertNotIn((node.func.value.id, node.func.attr), forbidden_calls, path.name)
            if path.name != "rng.py":
                self.assertFalse(imports_random, path.name)


if __name__ == "__main__":
    unittest.main()
