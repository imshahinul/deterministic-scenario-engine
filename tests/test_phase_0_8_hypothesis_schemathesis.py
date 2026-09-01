from __future__ import annotations

import ast
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import unittest

from hypothesis import find, given, settings, strategies as st
from hypothesis.strategies import SearchStrategy
import schemathesis
import yaml

from scenario_engine.dsl.compiler import compile_document
from scenario_engine.dsl.parser import parse_yaml
from scenario_engine.dsl.runtime import replay_scenario, run_scenario
from scenario_engine.integrations.hypothesis import ScenarioHypothesisCase, scenario_cases
from scenario_engine.integrations.schemathesis import (
    BoundSchemathesisCase, ScenarioBindingError, SchemathesisCaseBindings,
    UnsupportedHTTPBindingValueError, bind_case, operation_cases,
)
from scenario_engine.reference_packs.ecommerce import ecommerce_registry
from scenario_engine.result import ScenarioResult


ROOT = Path(__file__).parents[1]
SCENARIO = (ROOT / "examples/phase0_8_api_scenario.yaml").read_text()
OPENAPI = yaml.safe_load((ROOT / "examples/phase0_8_openapi.yaml").read_text())
INPUTS = {"customer_id": "cust-08", "email_domain": "example.test", "quantity": 4}
HSET = settings(max_examples=12, database=None, deadline=None)
BINDINGS = SchemathesisCaseBindings(
    headers={"X-Customer-ID": "state.customer_id"},
    body={"order_number": "state.order_number", "customer_email": "state.customer_email", "quantity": "state.quantity"},
)


def scenario_strategy(inputs=st.just(INPUTS), indexes=st.just(3)):
    return scenario_cases(SCENARIO, root_seed="phase08", run_indexes=indexes, inputs=inputs, plugins=ecommerce_registry())


def drawn(strategy):
    return find(strategy, lambda value: True, settings=HSET)


def operation():
    return schemathesis.openapi.from_dict(deepcopy(OPENAPI))["/orders"]["POST"]


class Phase08HypothesisSchemathesisTests(unittest.TestCase):
    def test_property_testing_extras_are_optional_and_core_dependencies_unchanged(self):
        project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
        self.assertEqual(project["dependencies"], ["PyYAML==6.0.3"])
        extras = project["optional-dependencies"]
        self.assertEqual(extras["pytest"], ["pytest>=9.1,<10"]); self.assertEqual(extras["sqlalchemy"], ["SQLAlchemy>=2.0,<3"])
        self.assertEqual(extras["hypothesis"], ["hypothesis>=6,<7"]); self.assertEqual(set(extras["schemathesis"]), {"hypothesis>=6,<7", "schemathesis>=4,<5"})

    def test_core_and_integrations_package_import_without_hypothesis_or_schemathesis(self):
        code = "import sys; sys.meta_path.insert(0,type('B',(),{'find_spec':lambda s,n,*a: (_ for _ in ()).throw(ImportError(n)) if n.split('.')[0] in {'hypothesis','schemathesis'} else None})()); import scenario_engine; import scenario_engine.integrations"
        completed = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_hypothesis_scenario_cases_returns_search_strategy(self):
        self.assertIsInstance(scenario_strategy(), SearchStrategy)

    def test_hypothesis_case_records_explicit_run_index_inputs_and_result(self):
        case = drawn(scenario_strategy()); self.assertIsInstance(case, ScenarioHypothesisCase); self.assertEqual(case.run_index, 3)
        self.assertEqual(dict(case.inputs), INPUTS); self.assertIsInstance(case.result, ScenarioResult); self.assertEqual(case.result.manifest.root_seed, "phase08")

    def test_same_drawn_context_reproduces_exact_result_and_bytes(self):
        case = drawn(scenario_strategy()); manual = run_scenario(compile_document(parse_yaml(case.yaml_text)), case.root_seed, case.run_index, locale=case.locale, inputs=dict(case.inputs), plugins=ecommerce_registry())
        self.assertEqual(case.result.normalized(), manual.normalized()); self.assertEqual(case.result.to_json_bytes(), manual.to_json_bytes())
        self.assertEqual(case.result.to_json_bytes(), replay_scenario(case.yaml_text, case.result.manifest, inputs=dict(case.inputs), plugins=ecommerce_registry()).to_json_bytes())

    def test_hypothesis_strategy_composes_with_explicit_plugin_registry(self):
        case = drawn(scenario_strategy()); self.assertEqual(case.result.final_state["status"], "order_created")
        self.assertIn("plugin:ecommerce.order_number", case.result.manifest.generator_versions)

    def test_hypothesis_drawn_inputs_are_defensively_isolated(self):
        original = {**INPUTS, "nested": {"items": [1, 2]}}; case = drawn(scenario_strategy(st.just(original))); before = case.result.to_json_bytes(); original["nested"]["items"].append(3); original["quantity"] = 9
        self.assertEqual(case.inputs["nested"]["items"], (1, 2)); self.assertEqual(case.inputs["quantity"], 4); self.assertEqual(case.result.to_json_bytes(), before)

    def test_hypothesis_adapter_does_not_bridge_hidden_randomness_into_engine(self):
        source = (ROOT / "src/scenario_engine/integrations/hypothesis.py").read_text(); tree = ast.parse(source)
        imports = {alias.name for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom)) for alias in node.names}
        self.assertNotIn("random", imports); self.assertNotIn("AddressedRNG", source); self.assertNotIn("randoms(", source)

    def test_hypothesis_adapter_does_not_use_example_database_or_example_method(self):
        source = (ROOT / "src/scenario_engine/integrations/hypothesis.py").read_text()
        for forbidden in (".example(", "DirectoryBasedExampleDatabase", '".hypothesis"', "database="): self.assertNotIn(forbidden, source)

    def test_case_bindings_apply_selected_normalized_result_values(self):
        scenario = drawn(scenario_strategy()); case = drawn(operation().as_strategy()); bind_case(case, scenario.result, BINDINGS)
        self.assertEqual(case.headers["X-Customer-ID"], "cust-08"); self.assertEqual(case.body["order_number"], scenario.result.final_state["order_number"]); self.assertEqual(case.body["quantity"], 4)

    def test_case_bindings_preserve_unbound_schemathesis_values(self):
        scenario = drawn(scenario_strategy()); case = drawn(operation().as_strategy()); before_note = case.body["note"]; before_query = deepcopy(case.query); bind_case(case, scenario.result, BINDINGS)
        self.assertEqual(case.body["note"], before_note); self.assertEqual(case.query, before_query)

    def test_missing_binding_source_path_raises_explicit_error(self):
        with self.assertRaises(ScenarioBindingError): bind_case(drawn(operation().as_strategy()), drawn(scenario_strategy()).result, SchemathesisCaseBindings(body={"x": "state.absent"}))

    def test_http_parameter_binding_rejects_unsupported_complex_value(self):
        with self.assertRaises(UnsupportedHTTPBindingValueError): bind_case(drawn(operation().as_strategy()), drawn(scenario_strategy()).result, SchemathesisCaseBindings(headers={"X": "history"}))

    def test_case_binding_does_not_mutate_scenario_result(self):
        result = drawn(scenario_strategy()).result; before = (result.normalized(), result.to_json_bytes(), result.manifest, result.trace(), result.provenance.normalized())
        bind_case(drawn(operation().as_strategy()), result, BINDINGS)
        self.assertEqual(before, (result.normalized(), result.to_json_bytes(), result.manifest, result.trace(), result.provenance.normalized()))

    def test_operation_cases_composes_with_schemathesis_operation_strategy(self):
        strategy = operation_cases(operation(), scenario_strategy(), BINDINGS); self.assertIsInstance(strategy, SearchStrategy); self.assertIsInstance(drawn(strategy), BoundSchemathesisCase)

    def test_operation_cases_preserves_operation_method_and_path_identity(self):
        case = drawn(operation_cases(operation(), scenario_strategy(), BINDINGS)).case
        self.assertEqual(case.method.upper(), "POST"); self.assertEqual(case.operation.path, "/orders")

    def test_local_openapi_from_dict_and_as_strategy_are_supported(self):
        op = operation(); self.assertIsInstance(op.as_strategy(), SearchStrategy); self.assertEqual(drawn(op.as_strategy()).operation.path, "/orders")

    def test_schemathesis_adapter_never_calls_network_or_executes_case(self):
        source = (ROOT / "src/scenario_engine/integrations/schemathesis.py").read_text()
        for forbidden in (".call(", ".call_and_validate(", "from_url", "requests", "httpx", "urllib", "socket"): self.assertNotIn(forbidden, source)

    def test_bound_api_case_preserves_scenario_replay_context(self):
        bound = drawn(operation_cases(operation(), scenario_strategy(), BINDINGS)); context = bound.scenario
        replayed = replay_scenario(context.yaml_text, context.result.manifest, inputs=dict(context.inputs), plugins=ecommerce_registry())
        self.assertEqual(context.result.to_json_bytes(), replayed.to_json_bytes())

    def test_hypothesis_shrinking_operates_on_explicit_scenario_inputs(self):
        strategy = scenario_strategy(st.fixed_dictionaries({"customer_id": st.just("c"), "email_domain": st.just("example.test"), "quantity": st.integers(0, 10)}), st.integers(0, 5))
        case = find(strategy, lambda item: item.inputs["quantity"] >= 4, settings=HSET); self.assertEqual(case.inputs["quantity"], 4)

    def test_ecommerce_plugin_scenario_composes_with_property_api_integration(self):
        bound = drawn(operation_cases(operation(), scenario_strategy(), BINDINGS)); state = bound.scenario.result.final_state
        self.assertEqual(bound.case.body["customer_email"], state["customer_email"]); self.assertEqual(bound.case.body["order_number"], state["order_number"]); self.assertIn("note", bound.case.body)

    def test_integration_does_not_change_manifest_or_result_bytes(self):
        case = drawn(scenario_strategy()); before = (case.result.manifest, case.result.normalized(), case.result.to_json_bytes()); bind_case(drawn(operation().as_strategy()), case.result, BINDINGS)
        outside = run_scenario(compile_document(parse_yaml(SCENARIO)), case.root_seed, case.run_index, inputs=dict(case.inputs), plugins=ecommerce_registry())
        self.assertEqual(before, (outside.manifest, outside.normalized(), outside.to_json_bytes()))

    def test_real_pytest_runs_hypothesis_and_local_schemathesis_composition(self):
        with tempfile.TemporaryDirectory(dir=Path.home() / "Developer/scenario-engine-audit") as directory:
            path = Path(directory) / "test_phase08_real.py"
            path.write_text("""from pathlib import Path\nimport yaml,schemathesis\nfrom hypothesis import given,settings,strategies as st\nfrom scenario_engine.integrations.hypothesis import scenario_cases\nfrom scenario_engine.integrations.schemathesis import SchemathesisCaseBindings,operation_cases\nfrom scenario_engine.reference_packs.ecommerce import ecommerce_registry\nfrom scenario_engine.dsl.runtime import replay_scenario\nROOT=Path(r'""" + str(ROOT) + """')\ny=(ROOT/'examples/phase0_8_api_scenario.yaml').read_text(); spec=yaml.safe_load((ROOT/'examples/phase0_8_openapi.yaml').read_text()); op=schemathesis.openapi.from_dict(spec)['/orders']['POST']\nss=scenario_cases(y,root_seed='real',run_indexes=st.integers(0,2),inputs=st.fixed_dictionaries({'customer_id':st.just('c'),'email_domain':st.just('example.test'),'quantity':st.integers(1,5)}),plugins=ecommerce_registry())\nb=SchemathesisCaseBindings(body={'quantity':'state.quantity','order_number':'state.order_number'})\n@given(operation_cases(op,ss,b))\n@settings(max_examples=5,database=None,deadline=None)\ndef test_real(x):\n assert x.case.body['quantity']==x.scenario.inputs['quantity']; assert x.scenario.result.to_json_bytes()==replay_scenario(x.scenario.yaml_text,x.scenario.result.manifest,inputs=dict(x.scenario.inputs),plugins=ecommerce_registry()).to_json_bytes()\n""")
            completed = subprocess.run([sys.executable, "-m", "pytest", "-q", str(path)], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_phase0_8_examples_and_all_prior_examples_remain_compatible(self):
        cases = [("phase0_1b_cart.yaml", None, None), ("phase0_3_resources.yaml", {"customer_id":"c","maximum_quantity":5}, None), ("phase0_4_control_flow.yaml", {"premium":True,"retry_count":1,"customer_id":"c"}, None)]
        for name, inputs, plugins in cases:
            text=(ROOT/"examples"/name).read_text(); result=run_scenario(compile_document(parse_yaml(text)),"compat",inputs=inputs,plugins=plugins); self.assertEqual(result.to_json_bytes(),replay_scenario(text,result.manifest,inputs=inputs,plugins=plugins).to_json_bytes())
        for name in ("phase0_5_oracle_fault.yaml", "phase0_6_sqlalchemy_rows.yaml"): self.assertIsNotNone(parse_yaml((ROOT/"examples"/name).read_text()))
        old=(ROOT/"examples/phase0_7_ecommerce_plugin.yaml").read_text(); old_inputs={"email_domain":"example.test"}; old_result=run_scenario(compile_document(parse_yaml(old)),"compat",inputs=old_inputs,plugins=ecommerce_registry()); self.assertEqual(old_result.to_json_bytes(),replay_scenario(old,old_result.manifest,inputs=old_inputs,plugins=ecommerce_registry()).to_json_bytes())
        new=drawn(scenario_strategy()); self.assertEqual(new.result.to_json_bytes(),replay_scenario(SCENARIO,new.result.manifest,inputs=dict(new.inputs),plugins=ecommerce_registry()).to_json_bytes()); self.assertEqual(OPENAPI["openapi"], "3.0.3")
