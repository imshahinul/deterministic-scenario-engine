from __future__ import annotations

import unittest
from decimal import Decimal
from pathlib import Path

from scenario_engine.canonical import canonical_scenario_hash
from scenario_engine.dsl import (ConstraintDefinitionError, ConstraintViolation,
    ResourceCycleError, ResourceResolutionError, ResourceValidationError,
    compile_document, parse_yaml, replay_scenario, resolve_resources, run_scenario)
from scenario_engine.expressions import (BooleanMany, BooleanNot, Divide, Equal,
    EvaluationEnvironment, ExpressionEvaluationError, GreaterThan, GreaterThanOrEqual,
    Length, LessThan, LessThanOrEqual, Literal, NotEqual, Subtract)
from scenario_engine.manifest import ReplayCompatibilityError
from scenario_engine.values import MISSING


BASE = '''dsl_version: 1
scenario: phase03
clock: {start: "2026-01-01T00:00:00Z"}
initial_state: {}
resources:
  customer: {id: {$input: customer_id}}
  checkout: {customer_id: {$ref: customer.id}}
validators:
  - {id: customer_type, resource: customer.id, kind: type, type: string}
constraints:
  - id: valid
    check: {$eq: [{$resource: customer.id}, {$resource: checkout.customer_id}]}
steps:
  - id: one
    write: {customer_id: {$resource: checkout.customer_id}}
    transition: null
'''


def run(text=BASE, inputs=None):
    if inputs is None: inputs = {"customer_id": "cust-1"}
    return run_scenario(compile_document(parse_yaml(text)), "seed", inputs=inputs)


class Phase03ResourcesConstraintsTests(unittest.TestCase):
    def test_external_input_resolves_into_named_resource(self):
        inputs = {"customer_id": "cust-123"}; result = run(inputs=inputs)
        self.assertEqual(result.resolved_resources.lookup("customer.id"), "cust-123"); self.assertEqual(inputs, {"customer_id": "cust-123"})

    def test_nested_resource_reference_graph_resolves_independent_of_mapping_order(self):
        one = resolve_resources({"b": {"v": {"$ref": "a.v"}}, "a": {"v": 1}}, {})
        two = resolve_resources({"a": {"v": 1}, "b": {"v": {"$ref": "a.v"}}}, {})
        self.assertEqual(one.normalized(), two.normalized()); self.assertEqual(one.hashes(), two.hashes())

    def test_resource_cycle_is_rejected_before_execution(self):
        with self.assertRaises(ResourceCycleError): resolve_resources({"a": {"$ref": "b"}, "b": {"$ref": "a"}}, {})

    def test_missing_external_input_is_rejected_before_execution(self):
        with self.assertRaises(ResourceResolutionError): run(inputs={})

    def test_resolved_resources_are_defensively_isolated(self):
        source = {"x": {"nested": [1]}}; resources = resolve_resources({"r": {"$input": "x"}}, source); source["x"]["nested"].append(2)
        snap = resources.snapshot(); snap["r"]["nested"].append(3); self.assertEqual(resources.lookup("r.nested"), [1])

    def test_unused_external_input_does_not_change_manifest_or_result(self):
        a = run(inputs={"customer_id": "x"}); b = run(inputs={"customer_id": "x", "unused": 9})
        self.assertEqual(a.manifest.input_resource_hashes, b.manifest.input_resource_hashes); self.assertEqual(a.normalized(), b.normalized())

    def test_manifest_hashes_consumed_inputs_and_resolved_resources(self):
        keys = set(run().manifest.input_resource_hashes); self.assertEqual(keys, {"input:customer_id", "resource:customer", "resource:checkout"})

    def test_resource_semantic_key_order_produces_same_hashes(self):
        self.assertEqual(resolve_resources({"r": {"a": 1, "b": 2}}, {}).hashes(), resolve_resources({"r": {"b": 2, "a": 1}}, {}).hashes())

    def test_changed_consumed_input_changes_resource_hashes_not_scenario_hash(self):
        a, b = run(inputs={"customer_id": "a"}), run(inputs={"customer_id": "b"})
        self.assertEqual(a.manifest.scenario_canonical_hash, b.manifest.scenario_canonical_hash); self.assertNotEqual(a.manifest.input_resource_hashes, b.manifest.input_resource_hashes)

    def test_exact_replay_with_matching_inputs_succeeds(self):
        original = run(); self.assertEqual(original.normalized(), replay_scenario(BASE, original.manifest, inputs={"customer_id": "cust-1"}).normalized())

    def test_replay_rejects_wrong_input_resource_hashes(self):
        with self.assertRaisesRegex(ReplayCompatibilityError, "input_resource_hashes"): replay_scenario(BASE, run().manifest, inputs={"customer_id": "wrong"})

    def test_required_validator_distinguishes_missing_from_null(self):
        text = BASE.replace("kind: type, type: string", "kind: required").replace("$input: customer_id", "$literal: null")
        self.assertIsNone(run(text).resolved_resources.lookup("customer.id"))
        with self.assertRaises(ResourceValidationError): run(text.replace("$literal: null", "$missing: true"))

    def test_type_validator_uses_semantic_types(self):
        text = BASE.replace("$input: customer_id", "$literal: true").replace("type: string", "type: integer")
        with self.assertRaises(ResourceValidationError): run(text)
        for literal, kind in (("true", "boolean"), ("1", "integer"), ('{$decimal: "1"}', "decimal"), ("null", "null"), ("{$missing: true}", "missing")):
            run(text.replace("$literal: true", f"$literal: {literal}").replace("type: integer", f"type: {kind}"))

    def test_range_validator_is_exact_for_integer_and_decimal(self):
        text = BASE.replace("kind: type, type: string", "kind: range, min: 1, max: {$decimal: '2.0'}").replace("$input: customer_id", "$literal: {$decimal: '2.0'}")
        run(text)
        with self.assertRaises(ResourceValidationError): run(text.replace("'2.0'", "'2.1'", 1))

    def test_length_validator_checks_string_list_and_map(self):
        for literal in ('"ab"', "[1, 2]", "{a: 1, b: 2}"):
            run(BASE.replace("kind: type, type: string", "kind: length, min: 2, max: 2").replace("$input: customer_id", f"$literal: {literal}"))

    def test_one_of_validator_uses_semantic_equality(self):
        text = BASE.replace("kind: type, type: string", "kind: one_of, values: [{a: 1, b: 2}]").replace("$input: customer_id", "$literal: {b: 2, a: 1}")
        run(text)

    def test_validation_failure_occurs_before_scenario_execution(self):
        with self.assertRaises(ResourceValidationError): run(inputs={"customer_id": 1})

    def test_true_cross_resource_constraint_allows_execution(self):
        self.assertEqual(run().final_state["customer_id"], "cust-1")

    def test_false_cross_resource_constraint_blocks_execution(self):
        with self.assertRaises(ConstraintViolation): run(BASE.replace("$eq", "$ne"))

    def test_constraint_requires_boolean_result(self):
        with self.assertRaises(ConstraintDefinitionError): run(BASE.replace("check: {$eq: [{$resource: customer.id}, {$resource: checkout.customer_id}]}", "check: {$literal: 1}"))

    def test_constraint_rejects_state_local_and_derived_references(self):
        for operator in ("$state", "$local", "$derived"):
            with self.assertRaises(Exception): parse_yaml(BASE.replace("{$eq: [{$resource: customer.id}, {$resource: checkout.customer_id}]}", "{" + operator + ": x}"))

    def test_resource_expression_reads_resolved_value_in_step(self):
        self.assertEqual(run(inputs={"customer_id": "exact"}).final_state["customer_id"], "exact")

    def test_subtraction_expression_preserves_integer_and_decimal_semantics(self):
        env = EvaluationEnvironment({}, {}, {}); self.assertEqual(Subtract(Literal(3), Literal(1)).evaluate(env), 2)
        self.assertEqual(Subtract(Literal(Decimal("3")), Literal(1)).evaluate(env), Decimal("2")); self.assertIsInstance(Subtract(Literal(3), Literal(Decimal("1"))).evaluate(env), Decimal)

    def test_division_expression_returns_decimal_and_rejects_zero(self):
        env = EvaluationEnvironment({}, {}, {}); self.assertEqual(Divide(Literal(5), Literal(2)).evaluate(env), Decimal("2.5"))
        with self.assertRaises(ExpressionEvaluationError): Divide(Literal(1), Literal(0)).evaluate(env)

    def test_comparison_expressions_use_strict_semantic_types(self):
        env = EvaluationEnvironment({}, {}, {}); pairs = [(Equal, 1, 1, True), (NotEqual, 1, 2, True), (LessThan, 1, Decimal("2"), True), (LessThanOrEqual, "a", "a", True), (GreaterThan, "b", "a", True), (GreaterThanOrEqual, 2, 2, True)]
        for cls, a, b, expected in pairs: self.assertEqual(cls(Literal(a), Literal(b)).evaluate(env), expected)
        with self.assertRaises(ExpressionEvaluationError): LessThan(Literal(1), Literal("1")).evaluate(env)

    def test_boolean_and_length_expressions_require_exact_types(self):
        env = EvaluationEnvironment({}, {}, {}); self.assertTrue(BooleanMany((Literal(True), Literal(True)), True).evaluate(env)); self.assertTrue(BooleanNot(Literal(False)).evaluate(env))
        for value in ("ab", [1], {"a": 1}): self.assertEqual(Length(Literal(value)).evaluate(env), len(value))
        with self.assertRaises(ExpressionEvaluationError): BooleanMany((Literal(1),), True).evaluate(env)

    def test_canonical_hash_includes_resource_validator_and_constraint_declarations(self):
        base = canonical_scenario_hash(BASE); self.assertNotEqual(base, canonical_scenario_hash(BASE.replace("customer_type", "customer_kind"))); self.assertNotEqual(base, canonical_scenario_hash(BASE.replace("id: valid", "id: valid2"))); self.assertNotEqual(base, canonical_scenario_hash(BASE.replace("checkout:", "basket:", 1).replace("checkout.customer_id", "basket.customer_id")))

    def test_phase0_3_example_and_phase0_1_example_both_run_and_replay(self):
        phase3 = Path("examples/phase0_3_resources.yaml").read_text(); r3 = run_scenario(compile_document(parse_yaml(phase3)), "s", inputs={"customer_id": "c", "maximum_quantity": 5}); self.assertEqual(r3.normalized(), replay_scenario(phase3, r3.manifest, inputs={"customer_id": "c", "maximum_quantity": 5}).normalized())
        old = Path("examples/phase0_1b_cart.yaml").read_text(); r1 = run_scenario(compile_document(parse_yaml(old)), "s"); self.assertEqual({}, dict(r1.manifest.input_resource_hashes)); self.assertEqual(r1.normalized(), replay_scenario(old, r1.manifest).normalized())


if __name__ == "__main__": unittest.main()
