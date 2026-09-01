from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scenario_engine.address import ExecutionAddress
from scenario_engine.canonical import canonical_scenario_hash
from scenario_engine.clock import LogicalClock
from scenario_engine.context import GenerationContext
from scenario_engine.dsl import compile_document, parse_yaml, replay_scenario, run_scenario
from scenario_engine.dsl.errors import DSLSchemaError
from scenario_engine.ids import DeterministicIDProvider
from scenario_engine.plugins import (
    GeneratorPlugin, PluginCompatibilityError, PluginDefinitionError,
    PluginExecutionError, PluginGenerationContext, PluginRegistry,
    PluginResultError, invoke_plugin,
)
from scenario_engine.reference_packs.ecommerce import ecommerce_registry
from scenario_engine.rng import DeterministicRNG
from scenario_engine.runner import ScenarioRunner, StepSpec
from scenario_engine.state import ScenarioState


ROOT = Path(__file__).parents[1]
EXAMPLE = ROOT / "examples" / "phase0_7_ecommerce_plugin.yaml"
INPUTS = {"email_domain": "example.test"}


def declaration(name="test.capture", version="1", args=""):
    suffix = f"\n          args:\n{args}" if args else ""
    return f'''dsl_version: 1
scenario: plugin_test
clock: {{start: "2026-01-01T00:00:00Z"}}
initial_state: {{source: state-value, output: null}}
steps:
  - id: generate_value
    generate:
      value:
        $plugin:
          name: {name}
          version: "{version}"{suffix}
    write: {{output: {{$local: value}}}}
    transition: null
'''


def run(text, registry, seed="phase07", inputs=None):
    return run_scenario(compile_document(parse_yaml(text)), seed, inputs=inputs, plugins=registry)


class PluginEcommerceTests(unittest.TestCase):
    def test_plugin_registry_requires_unique_names_and_explicit_versions(self):
        fn = lambda context, arguments: "x"
        for name in ("", " ", "Upper.name", "single"):
            with self.subTest(name=name), self.assertRaises(PluginDefinitionError): GeneratorPlugin(name, "1", fn)
        with self.assertRaises(PluginDefinitionError): GeneratorPlugin("test.valid", "", fn)
        plugin = GeneratorPlugin("test.valid", "1", fn)
        with self.assertRaises(PluginDefinitionError): PluginRegistry((plugin, plugin))

    def test_plugin_registry_order_is_semantically_irrelevant(self):
        a = GeneratorPlugin("test.a", "1", lambda c, a: "A")
        b = GeneratorPlugin("test.b", "1", lambda c, a: "B")
        left, right = PluginRegistry((a, b)), PluginRegistry((b, a))
        self.assertEqual(left.get("test.a"), right.get("test.a"))
        self.assertEqual(run(declaration("test.a"), left).to_json_bytes(), run(declaration("test.a"), right).to_json_bytes())

    def test_plugin_context_exposes_only_deterministic_generation_services(self):
        context = PluginGenerationContext(DeterministicRNG("s", ExecutionAddress("x", 0)), LogicalClock(datetime.now(timezone.utc)), DeterministicIDProvider("s"), ExecutionAddress("x", 0))
        self.assertEqual({"rng", "clock", "ids", "address"}, set(context.__slots__))
        self.assertFalse(hasattr(context, "state")); self.assertFalse(hasattr(context, "resources"))

    def test_plugin_invocation_uses_exact_execution_address(self):
        seen = []
        registry = PluginRegistry((GeneratorPlugin("test.capture", "1", lambda c, a: seen.append(c.address) or "x"),))
        run(declaration(), registry)
        address = seen[0]
        self.assertEqual(("plugin_test", 0, "generate_value", ("generate", "value")), (address.scenario_id, address.run_index, address.step_id, address.semantic_path))

    def test_same_plugin_same_context_replays_same_value(self):
        plugin = GeneratorPlugin("test.capture", "1", lambda c, a: c.rng.inclusive_int(1, 999999))
        registry = PluginRegistry((plugin,)); text = declaration()
        self.assertEqual(run(text, registry).to_json_bytes(), run(text, registry).to_json_bytes())

    def test_unrelated_generator_does_not_shift_plugin_output(self):
        registry = PluginRegistry((GeneratorPlugin("test.capture", "1", lambda c, a: c.rng.inclusive_int(1, 999999)),))
        text = declaration(); changed = text.replace("generate:\n", "generate:\n      unrelated: {$int: [1, 99]}\n")
        self.assertEqual(run(text, registry).runner.state.to_dict()["output"], run(changed, registry).runner.state.to_dict()["output"])

    def test_unused_registry_plugin_does_not_change_manifest_or_result(self):
        used = GeneratorPlugin("test.capture", "1", lambda c, a: "x")
        a = run(declaration(), PluginRegistry((used,)))
        b = run(declaration(), PluginRegistry((used, GeneratorPlugin("test.unused", "9", lambda c, a: "z"))))
        self.assertEqual(a.to_json_bytes(), b.to_json_bytes()); self.assertEqual(a.manifest, b.manifest)

    def test_missing_required_plugin_is_rejected_before_execution(self):
        with self.assertRaises(PluginCompatibilityError): run(declaration(), PluginRegistry())

    def test_plugin_version_mismatch_is_rejected_before_execution(self):
        registry = PluginRegistry((GeneratorPlugin("test.capture", "2", lambda c, a: "x"),))
        with self.assertRaises(PluginCompatibilityError): run(declaration(), registry)

    def test_manifest_records_only_invoked_plugin_versions(self):
        plugins = (GeneratorPlugin("test.capture", "1", lambda c, a: "x"), GeneratorPlugin("test.unused", "1", lambda c, a: "y"))
        versions = run(declaration(), PluginRegistry(plugins)).manifest.generator_versions
        self.assertEqual("1", versions["plugin:test.capture"]); self.assertNotIn("plugin:test.unused", versions)

    def test_plugin_arguments_read_state_resource_scope_and_literal(self):
        text = declaration(args="            state: {$state: source}\n            resource: {$resource: item}\n            literal: {$literal: literal-value}").replace("initial_state:", "resources: {item: {$input: item}}\ninitial_state:")
        registry = PluginRegistry((GeneratorPlugin("test.capture", "1", lambda c, a: "/".join(a.values())),))
        self.assertEqual("literal-value/resource-value/state-value", run(text, registry, inputs={"item":"resource-value"}).runner.state.to_dict()["output"])
        prefix, body = text.split("steps:\n", 1)
        scoped = (prefix + "subflows:\n  child:\n    steps:\n" +
                  "\n".join("      "+line for line in body.splitlines()) +
                  "\nsteps:\n  - id: call_child\n    call: {subflow: child, with: {scope_value: {$literal: scoped}}}\n    transition: null\n").replace("            literal: {$literal: literal-value}", "            literal: {$scope: scope_value}")
        self.assertIn("scoped", run(scoped, registry, inputs={"item":"resource-value"}).runner.state.to_dict()["output"])

    def test_plugin_arguments_reject_local_and_derived_references(self):
        for ref in ("$local", "$derived"):
            with self.subTest(ref=ref), self.assertRaises(DSLSchemaError): parse_yaml(declaration(args=f"            bad: {{{ref}: other}}"))

    def test_plugin_arguments_are_defensively_isolated(self):
        source = {"nested": [1, 2]}
        def mutate(context, arguments): arguments["value"]["nested"].append(3)
        context = GenerationContext("s", ExecutionAddress("x", 0), LogicalClock(datetime.now(timezone.utc)), DeterministicIDProvider("s"))
        with self.assertRaises(PluginExecutionError): invoke_plugin(GeneratorPlugin("test.mutate", "1", mutate), context, {"value": source})
        self.assertEqual({"nested":[1,2]}, source)

    def test_plugin_result_must_be_supported_semantic_value(self):
        for value in (1.5, object()):
            registry = PluginRegistry((GeneratorPlugin("test.capture", "1", lambda c, a, value=value: value),))
            with self.subTest(value=type(value).__name__), self.assertRaises(PluginResultError): run(declaration(), registry)

    def test_plugin_exception_preserves_whole_step_atomicity(self):
        class Failing:
            def generate(self, context): raise PluginExecutionError("stable")
        runner = ScenarioRunner("s", ExecutionAddress("x",0), ScenarioState({"value":0}), LogicalClock(datetime(2026,1,1,tzinfo=timezone.utc)))
        spec = StepSpec("fail", {"x":Failing()}, {}, {}, transition=lambda s:"next")
        before=runner.clock.current
        with self.assertRaises(PluginExecutionError): runner.run_step(spec)
        self.assertEqual({"value":0},runner.state.to_dict()); self.assertEqual(0,len(runner.history.records)); self.assertEqual([],runner.artifacts); self.assertEqual(before,runner.clock.current); self.assertIsNone(runner.next_step)

    def test_plugin_invocation_inside_repeated_subflow_has_distinct_addresses(self):
        seen=[]; registry=PluginRegistry((GeneratorPlugin("test.capture","1",lambda c,a: seen.append(c.address) or len(seen)),))
        body=declaration().split("steps:\n",1)[1]
        text=declaration().split("steps:\n",1)[0]+"subflows:\n  child:\n    steps:\n"+"\n".join("      "+x for x in body.splitlines())+"\nsteps:\n  - id: repeat_child\n    repeat: {count: {$literal: 2}, max: 2, subflow: child}\n    transition: null\n"
        run(text,registry); self.assertEqual([(0,),(1,)], [x.repetition_indexes for x in seen])

    def test_plugin_scenario_exact_replay_requires_matching_registry(self):
        text=EXAMPLE.read_text(); result=run(text,ecommerce_registry(),inputs=INPUTS)
        self.assertEqual(result.to_json_bytes(), replay_scenario(text,result.manifest,inputs=INPUTS,plugins=ecommerce_registry()).to_json_bytes())
        with self.assertRaises(PluginCompatibilityError): replay_scenario(text,result.manifest,inputs=INPUTS,plugins=PluginRegistry())

    def test_plugin_declaration_name_version_and_args_affect_canonical_hash(self):
        base=declaration(args="            a: {$literal: 1}\n            b: {$literal: 2}")
        self.assertNotEqual(canonical_scenario_hash(base),canonical_scenario_hash(base.replace("test.capture","test.changed")))
        self.assertNotEqual(canonical_scenario_hash(base),canonical_scenario_hash(base.replace('version: "1"','version: "2"')))
        self.assertNotEqual(canonical_scenario_hash(base),canonical_scenario_hash(base.replace("$literal: 1","$literal: 3")))
        self.assertEqual(canonical_scenario_hash(base),canonical_scenario_hash(base.replace("            a: {$literal: 1}\n            b: {$literal: 2}","            b: {$literal: 2}\n            a: {$literal: 1}")))

    def test_ecommerce_pack_import_has_no_registration_side_effect(self):
        with self.assertRaises(PluginCompatibilityError): run(EXAMPLE.read_text(),PluginRegistry(),inputs=INPUTS)
        self.assertIsNot(ecommerce_registry(),ecommerce_registry())

    def test_ecommerce_reference_plugins_pass_determinism_source_audit(self):
        path=ROOT/"src/scenario_engine/reference_packs/ecommerce.py"; source=path.read_text(); ast.parse(source)
        for forbidden in ("random","secrets","uuid4","datetime.now","time.time","os.environ","subprocess","eval(","exec(","open("):
            self.assertNotIn(forbidden,source)

    def test_ecommerce_customer_email_is_deterministic(self):
        text=EXAMPLE.read_text(); a=run(text,ecommerce_registry(),inputs=INPUTS); b=run(text,ecommerce_registry(),inputs=INPUTS)
        self.assertEqual(a.runner.state.to_dict()["customer_email"],b.runner.state.to_dict()["customer_email"])

    def test_ecommerce_sku_order_and_tracking_generators_are_addressed(self):
        state=run(EXAMPLE.read_text(),ecommerce_registry(),inputs=INPUTS).runner.state.to_dict()
        self.assertRegex(state["sku"],r"^TST-[0-9]{6}$"); self.assertRegex(state["order_number"],r"^ORD-"); self.assertRegex(state["tracking_number"],r"^SYN-")

    def test_ecommerce_reference_scenario_runs_state_consistent_history(self):
        result=run(EXAMPLE.read_text(),ecommerce_registry(),inputs=INPUTS); state=result.runner.state.to_dict()
        self.assertEqual("shipped",state["status"]); self.assertTrue(state["paid"]); self.assertEqual(4,len(result.runner.history.records)); self.assertEqual(4,len(result.runner.artifacts))

    def test_ecommerce_reference_scenario_replays_exact_stable_bytes(self):
        text=EXAMPLE.read_text(); result=run(text,ecommerce_registry(),inputs=INPUTS)
        self.assertEqual(result.to_json_bytes(),replay_scenario(text,result.manifest,inputs=INPUTS,plugins=ecommerce_registry()).to_json_bytes())

    def test_real_pytest_harness_accepts_explicit_plugin_registry(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"test_plugin.py"; path.write_text('pytest_plugins=["scenario_engine.pytest_plugin"]\nfrom pathlib import Path\nfrom scenario_engine.reference_packs.ecommerce import ecommerce_registry\ndef test_it(scenario_engine):\n t=Path("examples/phase0_7_ecommerce_plugin.yaml").read_text(); i={"email_domain":"example.test"}; r=scenario_engine.run_text(t,root_seed="s",inputs=i,plugins=ecommerce_registry()); assert r.to_json_bytes()==scenario_engine.replay_text(t,r.manifest,inputs=i,plugins=ecommerce_registry()).to_json_bytes()\n')
            completed=subprocess.run([sys.executable,"-m","pytest","-q",str(path)],capture_output=True,text=True)
            self.assertEqual(0,completed.returncode,completed.stdout+completed.stderr)

    def test_phase0_7_example_and_all_prior_examples_remain_compatible(self):
        cases=(("phase0_1b_cart.yaml",None),("phase0_3_resources.yaml",{"customer_id":"c","maximum_quantity":5}),("phase0_4_control_flow.yaml",{"premium":True,"retry_count":1,"customer_id":"c"}))
        for name,inputs in cases:
            text=(ROOT/"examples"/name).read_text(); result=run_scenario(compile_document(parse_yaml(text)),"s",inputs=inputs); self.assertEqual(result.to_json_bytes(),replay_scenario(text,result.manifest,inputs=inputs).to_json_bytes())
        self.assertEqual("shipped",run(EXAMPLE.read_text(),ecommerce_registry(),inputs=INPUTS).runner.state.to_dict()["status"])


if __name__ == "__main__": unittest.main()
