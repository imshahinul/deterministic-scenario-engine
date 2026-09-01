from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path
from types import MappingProxyType
import unittest

import scenario_engine
from scenario_engine import (
    ENGINE_VERSION, MISSING, ExecutionAddress, GeneratorPlugin, LogicalID,
    PluginGenerationContext, PluginRegistry, ReproducibilityManifest,
    ScenarioEngineError, ScenarioResult, canonical_scenario_bytes,
    canonical_scenario_hash, canonical_scenario_payload, compile_document,
    evaluate_scenario, parse_yaml, parse_yaml_file, replay_scenario, run_scenario,
)
from scenario_engine.adapters.sqlalchemy import SqlAlchemyMaterializerError
from scenario_engine.control_flow import ControlFlowError
from scenario_engine.dsl.errors import DSLError
from scenario_engine.expressions import (
    Add, EvaluationEnvironment, ExpressionEvaluationError, Literal, LocalRef,
    ScopeResolutionError, StateRef,
)
from scenario_engine.faults import FaultError
from scenario_engine.integrations.hypothesis import HypothesisIntegrationError
from scenario_engine.integrations.schemathesis import SchemathesisIntegrationError
from scenario_engine.invariants import InvariantError, InvariantViolation
from scenario_engine.manifest import ReplayCompatibilityError
from scenario_engine.oracle import OracleError
from scenario_engine.plugins import PluginError, PluginExecutionError, PluginResultError
from scenario_engine.resources import ResourceError
from scenario_engine.validation import ConstraintError, ResourceValidationError


ROOT = Path(__file__).parents[1]
SRC = ROOT / "src"

PUBLIC_EXPORTS = [
    "ENGINE_VERSION", "MISSING", "LogicalID", "ExecutionAddress",
    "ScenarioResult", "ReproducibilityManifest", "parse_yaml",
    "parse_yaml_file", "compile_document", "run_scenario", "replay_scenario",
    "evaluate_scenario", "canonical_scenario_payload", "canonical_scenario_bytes",
    "canonical_scenario_hash", "GeneratorPlugin", "PluginRegistry",
    "PluginGenerationContext", "ScenarioEngineError", "DSLError",
    "DSLParseError", "DSLSchemaError", "DSLCompilationError",
    "ExpressionEvaluationError", "ResourceError", "ResourceValidationError",
    "ConstraintError", "ControlFlowError", "InvariantError", "FaultError",
    "OracleError", "ReplayCompatibilityError", "PluginError",
]


class Phase10BPublicAPIErrorContractTests(unittest.TestCase):
    def test_exact_canonical_top_level_exports(self):
        self.assertEqual(scenario_engine.__all__, PUBLIC_EXPORTS)
        for name in PUBLIC_EXPORTS:
            self.assertTrue(hasattr(scenario_engine, name), name)

    def test_kernel_construction_internals_are_not_exported(self):
        excluded = {
            "CandidateStep", "ScenarioRunner", "ScenarioState", "StepSpec",
            "LogicalClock", "DeterministicRNG", "DeterministicIDProvider",
            "MAX_REPEAT_COUNT",
        }
        self.assertTrue(excluded.isdisjoint(scenario_engine.__all__))

    def test_primary_user_journey_is_top_level_importable_and_operational(self):
        text = (ROOT / "examples" / "phase0_1b_cart.yaml").read_text(encoding="utf-8")
        compiled = compile_document(parse_yaml(text))
        result = run_scenario(compiled, "phase1.0b")
        evaluation = evaluate_scenario(compiled, "phase1.0b")
        replayed = replay_scenario(text, result.manifest)
        self.assertIsInstance(result, ScenarioResult)
        self.assertEqual(result.to_json_bytes(), replayed.to_json_bytes())
        self.assertEqual(result.to_json_bytes(), evaluation.result.to_json_bytes())

    def test_core_import_does_not_eagerly_import_optional_dependencies(self):
        code = """
            import sys
            import scenario_engine
            forbidden = ('sqlalchemy', 'pytest', 'hypothesis', 'schemathesis')
            assert not [name for name in sys.modules if name.split('.')[0] in forbidden]
        """
        completed = subprocess.run(
            [sys.executable, "-I", "-c", f"import sys; sys.path.insert(0, {str(SRC)!r});\n{textwrap.dedent(code)}"],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_public_error_categories_share_root_and_value_compatibility(self):
        categories = (
            DSLError, ExpressionEvaluationError, ResourceError,
            ResourceValidationError, ConstraintError, ControlFlowError,
            InvariantError, FaultError, OracleError, ReplayCompatibilityError,
            PluginError, SqlAlchemyMaterializerError, HypothesisIntegrationError,
            SchemathesisIntegrationError,
        )
        for category in categories:
            with self.subTest(category=category.__name__):
                self.assertTrue(issubclass(category, ScenarioEngineError))
                self.assertTrue(issubclass(category, ValueError))

    def test_invariant_diagnostic_fields_are_stable(self):
        error = InvariantViolation("inventory_nonnegative", "checkout", "0/checkout")
        self.assertEqual(error.invariant_id, "inventory_nonnegative")
        self.assertEqual(error.step_id, "checkout")
        self.assertEqual(error.execution_address, "0/checkout")

    def test_missing_references_are_stable_engine_errors_not_key_errors(self):
        env = EvaluationEnvironment(MappingProxyType({}), MappingProxyType({}), MappingProxyType({}))
        cases = (
            (StateRef("missing"), "unknown semantic reference: namespace=state name=missing"),
            (LocalRef("missing"), "unknown semantic reference: namespace=local name=missing"),
        )
        for expression, expected in cases:
            messages = []
            for _ in range(2):
                with self.assertRaises(ScopeResolutionError) as caught:
                    expression.evaluate(env)
                self.assertNotIsInstance(caught.exception, KeyError)
                messages.append(str(caught.exception))
            self.assertEqual(messages, [expected, expected])

    def test_incompatible_add_is_stable_engine_error_not_raw_type_error(self):
        expression = Add(Literal(1), Literal("one"))
        env = EvaluationEnvironment({}, {}, {})
        messages = []
        for _ in range(2):
            with self.assertRaises(ExpressionEvaluationError) as caught:
                expression.evaluate(env)
            self.assertNotIsInstance(caught.exception, TypeError)
            messages.append(str(caught.exception))
        self.assertEqual(messages, [
            "incompatible operands for $add: int, str",
            "incompatible operands for $add: int, str",
        ])

    def test_plugin_execution_and_result_errors_share_plugin_family(self):
        self.assertTrue(issubclass(PluginExecutionError, PluginError))
        self.assertTrue(issubclass(PluginExecutionError, ScenarioEngineError))
        self.assertTrue(issubclass(PluginExecutionError, RuntimeError))
        self.assertTrue(issubclass(PluginResultError, PluginError))
        self.assertTrue(issubclass(PluginResultError, ScenarioEngineError))
        self.assertTrue(issubclass(PluginResultError, TypeError))

    def test_pytest_plugin_missing_dependency_has_intentional_error(self):
        code = """
            import importlib.abc
            import sys
            class BlockPytest(importlib.abc.MetaPathFinder):
                def find_spec(self, fullname, path, target=None):
                    if fullname == 'pytest' or fullname.startswith('pytest.'):
                        error = ModuleNotFoundError("No module named 'pytest'")
                        error.name = 'pytest'
                        raise error
                    return None
            sys.meta_path.insert(0, BlockPytest())
            try:
                import scenario_engine.pytest_plugin
            except Exception as error:
                assert type(error).__name__ == 'PytestIntegrationError', type(error)
                assert isinstance(error, ImportError)
                assert str(error) == "pytest integration requires the optional 'pytest' extra"
            else:
                raise AssertionError('pytest integration unexpectedly imported')
        """
        completed = subprocess.run(
            [sys.executable, "-I", "-c", f"import sys; sys.path.insert(0, {str(SRC)!r});\n{textwrap.dedent(code)}"],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
