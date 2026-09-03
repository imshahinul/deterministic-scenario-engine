from __future__ import annotations

from dataclasses import fields
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN, ROUND_UP, getcontext, localcontext
from hashlib import sha256
from pathlib import Path
import unittest

from scenario_engine import (
    ENGINE_VERSION, ReproducibilityManifest, compile_document, parse_yaml,
    replay_scenario, run_scenario,
)
from scenario_engine.dsl import DSLParseError, DSLSchemaError
from scenario_engine.expressions import (
    Add, Divide, EvaluationEnvironment, ExpressionEvaluationError, Literal,
    Multiply, Subtract, SumField,
)
from scenario_engine.manifest import ReplayCompatibilityError


ROOT = Path(__file__).parents[1]
CART_HASH = "cffc2e482f304ab18d39f96166e3e1be78b117a86bf0ce8ad0e22973677001b5"
FLOW_HASH = "86511d8c750272283eb1039a6e1039c8faa11cb5945c76aec41d9f5a71588e2b"
ENV = EvaluationEnvironment({}, {}, {})


def document(initial: str = "{}", steps: str | None = None, extra: str = "") -> str:
    return (
        "dsl_version: 1\nscenario: contract\n"
        "clock: {start: '2026-01-01T00:00:00Z'}\n"
        f"initial_state: {initial}\n"
        f"steps:\n{steps or '  - {id: done, transition: null}\n'}"
        f"{extra}"
    )


class YAMLContractTests(unittest.TestCase):
    def test_duplicate_keys_at_all_relevant_depths_are_parse_errors(self):
        cases = {
            "root": document() + "scenario: duplicate\n",
            "step": document(steps="  - id: done\n    id: duplicate\n    transition: null\n"),
            "expression": document(steps="  - id: done\n    write:\n      x: {$add: [{$literal: 1}, {$literal: 2}], $add: [{$literal: 3}, {$literal: 4}]}\n    transition: null\n"),
            "generator": document(steps="  - id: done\n    generate:\n      x: {$int: [1, 2], $int: [3, 4]}\n    transition: null\n"),
            "resource": document(extra="resources:\n  customer: {$literal: {id: 1, id: 2}}\n"),
            "semantic": document(initial="{nested: {value: 1, value: 2}}"),
        }
        for key, source in cases.items():
            with self.subTest(key=key), self.assertRaisesRegex(DSLParseError, "duplicate YAML mapping key"):
                parse_yaml(source)

    def test_aliases_and_merge_keys_are_rejected_before_construction(self):
        alias = document(initial="&state {x: 1}", steps="  - id: done\n    write: *state\n    transition: null\n")
        merge = document(initial="{x: 1}", steps="  - id: done\n    write:\n      <<: &writes {x: {$literal: 2}}\n    transition: null\n")
        with self.assertRaisesRegex(DSLParseError, "aliases are not supported"):
            parse_yaml(alias)
        with self.assertRaisesRegex(DSLParseError, "merge keys are not supported"):
            parse_yaml(merge)

    def test_scalar_resolution_is_narrow_and_semantic_boundaries_remain_strict(self):
        parsed = parse_yaml(document(initial="{truth: true, falsehood: false, yes_word: yes, on_word: on, integer: 12, legacy_integer: 01, nothing: null}"))
        self.assertEqual(parsed.initial_state, {
            "truth": True, "falsehood": False, "yes_word": "yes", "on_word": "on",
            "integer": 12, "legacy_integer": "01", "nothing": None,
        })
        with self.assertRaisesRegex(DSLSchemaError, "float semantic values are forbidden"):
            parse_yaml(document(initial="{value: 1.5}"))
        with self.assertRaisesRegex(DSLSchemaError, "mapping keys must be strings"):
            parse_yaml(document(initial="{1: value}"))

    def test_grammar_root_version_step_and_declaration_shapes_are_frozen(self):
        with self.assertRaisesRegex(DSLSchemaError, "unknown key"):
            parse_yaml(document() + "unknown: true\n")
        with self.assertRaisesRegex(DSLSchemaError, "missing required key"):
            parse_yaml(document().replace("initial_state: {}\n", ""))
        for version in ("true", "2", "'1'"):
            with self.subTest(version=version), self.assertRaises(Exception):
                parse_yaml(document().replace("dsl_version: 1", f"dsl_version: {version}"))
        with self.assertRaisesRegex(DSLSchemaError, "exactly one executable"):
            parse_yaml(document(steps="  - id: bad\n    call: {subflow: x}\n    write: {}\n    transition: null\n", extra="subflows:\n  x:\n    steps: [{id: x_done, transition: null}]\n"))
        for declaration in ("resources: {}", "constraints: []", "subflows: {}"):
            with self.subTest(declaration=declaration), self.assertRaises(DSLSchemaError):
                parse_yaml(document(extra=declaration + "\n"))
        parse_yaml(document(extra="validators: []\ninvariants: []\nfaults: []\noracle: {expected: {constraints: [], invariants: []}}\n"))


class ArithmeticContractTests(unittest.TestCase):
    def test_supported_numeric_matrix_and_result_types(self):
        cases = (
            (Add, 2, 3, 5, int), (Subtract, 7, 2, 5, int),
            (Multiply, 3, 4, 12, int), (Divide, 1, 2, Decimal("0.5"), Decimal),
            (Add, 2, Decimal("0.5"), Decimal("2.5"), Decimal),
            (Subtract, Decimal("2.5"), 1, Decimal("1.5"), Decimal),
            (Multiply, Decimal("2.5"), 2, Decimal("5.0"), Decimal),
        )
        for operation, left, right, expected, expected_type in cases:
            with self.subTest(operation=operation.__name__, left=left, right=right):
                actual = operation(Literal(left), Literal(right)).evaluate(ENV)
                self.assertEqual(actual, expected)
                self.assertIs(type(actual), expected_type)

    def test_unsupported_operands_have_deterministic_engine_errors(self):
        unsupported = (("x", "y"), ([1], [2]), (True, 1), (None, 1))
        for operation in (Add, Subtract, Multiply, Divide):
            for left, right in unsupported:
                with self.subTest(operation=operation.__name__, left=left), self.assertRaisesRegex(ExpressionEvaluationError, r"incompatible operands for \$"):
                    operation(Literal(left), Literal(right)).evaluate(ENV)

    def test_division_by_zero_is_stable(self):
        with self.assertRaisesRegex(ExpressionEvaluationError, r"^\$div division by zero$"):
            Divide(Literal(1), Literal(0)).evaluate(ENV)

    def test_decimal_arithmetic_ignores_ambient_context(self):
        expressions = (
            Divide(Literal(Decimal("1")), Literal(Decimal("7"))),
            SumField(Literal(({"amount": Decimal("1.1234567890123456789012345678")},
                              {"amount": Decimal("2.1234567890123456789012345678")})), "amount"),
        )
        outputs = []
        original = getcontext().copy()
        try:
            for precision, rounding in ((3, ROUND_DOWN), (50, ROUND_UP)):
                getcontext().prec = precision
                getcontext().rounding = rounding
                outputs.append(tuple(expression.evaluate(ENV) for expression in expressions))
        finally:
            getcontext().prec = original.prec
            getcontext().rounding = original.rounding
        expected = (Decimal("0.1428571428571428571428571429"), Decimal("3.246913578024691357802469136"))
        self.assertEqual(outputs, [expected, expected])


class ResultManifestCompatibilityTests(unittest.TestCase):
    def test_result_schema_alias_and_canonical_byte_rules_are_exact(self):
        source = (ROOT / "examples/phase0_1b_cart.yaml").read_text(encoding="utf-8")
        result = run_scenario(compile_document(parse_yaml(source)), "s")
        self.assertEqual(set(result.normalized()), {"artifacts", "clock", "history", "manifest", "next", "scenario_id", "state", "terminal_transition"})
        self.assertEqual(result.normalized()["next"], result.normalized()["terminal_transition"])
        self.assertFalse(result.to_json_bytes().endswith(b"\n"))
        self.assertEqual(result.to_json_bytes(), result.to_json().encode("utf-8"))
        self.assertEqual(sha256(result.to_json_bytes()).hexdigest(), CART_HASH)

    def test_structured_control_flow_golden_hash_is_literal(self):
        source = (ROOT / "examples/phase0_4_control_flow.yaml").read_text(encoding="utf-8")
        result = run_scenario(compile_document(parse_yaml(source)), "s", inputs={"premium": True, "retry_count": 2, "customer_id": "customer-1"})
        self.assertEqual(sha256(result.to_json_bytes()).hexdigest(), FLOW_HASH)

    def test_manifest_schema_types_order_and_validation_are_exact(self):
        source = (ROOT / "examples/phase0_1b_cart.yaml").read_text(encoding="utf-8")
        manifest = run_scenario(compile_document(parse_yaml(source)), "s").manifest
        self.assertEqual(tuple(field.name for field in fields(ReproducibilityManifest)), (
            "root_seed", "scenario_canonical_hash", "engine_version", "dsl_version",
            "input_resource_hashes", "domain_pack_versions", "generator_versions",
            "rng_algorithm_version", "id_algorithm_version", "locale",
            "reference_clock_start", "run_index",
        ))
        self.assertEqual(list(manifest.normalized()), sorted(manifest.normalized()))
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            ReproducibilityManifest("s", "0" * 64, ENGINE_VERSION, 1, reference_clock_start=datetime(2026, 1, 1))

    def test_exact_engine_and_plugin_compatibility_fail_explicitly(self):
        source = (ROOT / "examples/phase0_1b_cart.yaml").read_text(encoding="utf-8")
        result = run_scenario(compile_document(parse_yaml(source)), "s")
        values = {field.name: getattr(result.manifest, field.name) for field in fields(ReproducibilityManifest)}
        values["engine_version"] = "incompatible"
        with self.assertRaisesRegex(ReplayCompatibilityError, "engine_version mismatch"):
            replay_scenario(source, ReproducibilityManifest(**values))

    def test_advanced_oracle_provenance_result_is_stable(self):
        source = (ROOT / "examples/phase0_5_oracle_fault.yaml").read_text(encoding="utf-8").replace("enabled: true", "enabled: false")
        first = run_scenario(compile_document(parse_yaml(source)), "phase1.0c")
        second = run_scenario(compile_document(parse_yaml(source)), "phase1.0c")
        self.assertIn("provenance", first.normalized())
        self.assertEqual(first.to_json_bytes(), second.to_json_bytes())
        self.assertEqual(
            sha256(first.to_json_bytes()).hexdigest(),
            "5760aee1293d2d264d841621de08734358b3eb4ca54ef3e08e5a0b97f8f16cdd",
        )


if __name__ == "__main__":
    unittest.main()
