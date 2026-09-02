from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import re
import unittest

import scenario_engine
from scenario_engine import compile_document, evaluate_scenario, parse_yaml, replay_scenario, run_scenario
from scenario_engine.reference_packs.ecommerce import ecommerce_registry


ROOT = Path(__file__).parents[1]
DOCS = (
    "quickstart.md", "dsl-reference.md", "determinism.md", "reproducibility.md",
    "testing-oracle.md", "plugins.md", "sqlalchemy.md", "hypothesis.md",
    "schemathesis.md", "api.md", "security-and-non-goals.md", "compatibility.md",
)
EXAMPLES = (
    "cart.yaml", "resources.yaml", "control_flow.yaml", "oracle_fault.yaml",
    "sqlalchemy_rows.yaml", "ecommerce.yaml", "api_scenario.yaml", "openapi.yaml",
)
PUBLIC_EXPORTS = [
    "ENGINE_VERSION", "MISSING", "LogicalID", "ExecutionAddress", "ScenarioResult",
    "ReproducibilityManifest", "parse_yaml", "parse_yaml_file", "compile_document",
    "run_scenario", "replay_scenario", "evaluate_scenario",
    "canonical_scenario_payload", "canonical_scenario_bytes", "canonical_scenario_hash",
    "GeneratorPlugin", "PluginRegistry", "PluginGenerationContext",
    "ScenarioEngineError", "DSLError", "DSLParseError", "DSLSchemaError",
    "DSLCompilationError", "ExpressionEvaluationError", "ResourceError",
    "ResourceValidationError", "ConstraintError", "ControlFlowError",
    "InvariantError", "FaultError", "OracleError", "ReplayCompatibilityError",
    "PluginError",
]
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^]]+\]\(([^)]+)\)")


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class Phase10DDocumentationExampleTests(unittest.TestCase):
    def test_required_documentation_and_readme_links_exist(self):
        readme = ROOT / "README.md"
        self.assertTrue(readme.is_file())
        source = text(readme)
        for name in DOCS:
            self.assertTrue((ROOT / "docs" / name).is_file(), name)
            self.assertIn(f"docs/{name}", source)

    def test_every_local_markdown_link_resolves(self):
        for markdown in (ROOT / "README.md", *(ROOT / "docs").glob("*.md")):
            for target in MARKDOWN_LINK.findall(text(markdown)):
                target = target.split("#", 1)[0]
                if not target or "://" in target or target.startswith("mailto:"):
                    continue
                with self.subTest(markdown=markdown.name, target=target):
                    self.assertTrue((markdown.parent / target).resolve().exists())

    def test_canonical_public_examples_exist_and_are_frozen_copies(self):
        historical = (
            "phase0_1b_cart.yaml", "phase0_3_resources.yaml", "phase0_4_control_flow.yaml",
            "phase0_5_oracle_fault.yaml", "phase0_6_sqlalchemy_rows.yaml",
            "phase0_7_ecommerce_plugin.yaml", "phase0_8_api_scenario.yaml",
            "phase0_8_openapi.yaml",
        )
        for public, prior in zip(EXAMPLES, historical, strict=True):
            with self.subTest(public=public):
                self.assertEqual(text(ROOT / "examples" / public), text(ROOT / "examples" / prior))

    def test_public_core_examples_execute_replay_and_repeat_deterministically(self):
        cases = (
            ("cart.yaml", None),
            ("resources.yaml", {"customer_id": "docs-customer", "maximum_quantity": 5}),
            ("control_flow.yaml", {"premium": True, "retry_count": 2, "customer_id": "docs-customer"}),
            ("sqlalchemy_rows.yaml", None),
            ("api_scenario.yaml", {"customer_id": "docs-customer", "email_domain": "example.test", "quantity": 2}),
        )
        for name, inputs in cases:
            registry = ecommerce_registry() if name == "api_scenario.yaml" else None
            source = text(ROOT / "examples" / name)
            scenario = compile_document(parse_yaml(source))
            first = run_scenario(scenario, "phase1.0d", inputs=inputs, plugins=registry)
            second = run_scenario(scenario, "phase1.0d", inputs=inputs, plugins=registry)
            replayed = replay_scenario(source, first.manifest, inputs=inputs, plugins=registry)
            with self.subTest(name=name):
                self.assertEqual(first.to_json_bytes(), second.to_json_bytes())
                self.assertEqual(first.to_json_bytes(), replayed.to_json_bytes())

    def test_frozen_public_cart_and_control_flow_golden_hashes(self):
        cart = run_scenario(compile_document(parse_yaml(text(ROOT / "examples/cart.yaml"))), "s")
        flow_text = text(ROOT / "examples/control_flow.yaml")
        flow = run_scenario(
            compile_document(parse_yaml(flow_text)), "s",
            inputs={"premium": True, "retry_count": 2, "customer_id": "customer-1"},
        )
        self.assertEqual(sha256(cart.to_json_bytes()).hexdigest(), "ea85ecfe3d6014f10481637db4e8a137d00ffab0bdcfe4ed070f0b1404ee123e")
        self.assertEqual(sha256(flow.to_json_bytes()).hexdigest(), "73de01131fa12f904dee388a5ba04d11f8001ddde2a6d6b94e10b0ded0a75c61")

    def test_oracle_and_ecommerce_examples(self):
        oracle = compile_document(parse_yaml(text(ROOT / "examples/oracle_fault.yaml")))
        evaluation = evaluate_scenario(oracle, "phase1.0d")
        self.assertTrue(evaluation.report.passed)
        source = text(ROOT / "examples/ecommerce.yaml")
        result = run_scenario(
            compile_document(parse_yaml(source)), "phase1.0d",
            inputs={"email_domain": "example.test"}, plugins=ecommerce_registry(),
        )
        self.assertEqual(result.final_state["status"], "shipped")
        self.assertEqual(
            result.to_json_bytes(),
            replay_scenario(source, result.manifest, inputs={"email_domain": "example.test"}, plugins=ecommerce_registry()).to_json_bytes(),
        )

    def test_api_reference_matches_exact_frozen_top_level_contract(self):
        self.assertEqual(scenario_engine.__all__, PUBLIC_EXPORTS)
        api = text(ROOT / "docs/api.md")
        block = api.split("## Exact canonical top-level names", 1)[1].split("```text", 1)[1].split("```", 1)[0]
        self.assertEqual([line.strip() for line in block.splitlines() if line.strip()], PUBLIC_EXPORTS)

    def test_documented_plugin_and_schemathesis_boundaries_are_truthful(self):
        plugin = text(ROOT / "docs/plugins.md").lower()
        schemathesis = text(ROOT / "docs/schemathesis.md").lower()
        self.assertIn("no:\n\n- automatic global registration", plugin)
        self.assertIn("does not send http requests", schemathesis)
        self.assertIn("does not call the case", schemathesis)

    def test_normative_compatibility_contract_remains_unchanged(self):
        expected = text(ROOT / "docs/compatibility.md")
        self.assertEqual(
            sha256(expected.encode()).hexdigest(),
            "1a392e67f1282e721ce0ccd8d183edc56a691db30210f94c37e11f8a41043d28",
        )


if __name__ == "__main__":
    unittest.main()
