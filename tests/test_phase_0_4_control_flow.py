from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scenario_engine.canonical import canonical_scenario_hash
from scenario_engine.dsl import (BranchConditionError, RepeatCountError, RepeatLimitError,
    ScopeResolutionError, SubflowCycleError, UnknownSubflowError, compile_document,
    parse_yaml, replay_scenario, run_scenario)


def scenario(steps, subflows, initial="{}", resources=""):
    return f'''dsl_version: 1
scenario: phase04_test
clock: {{start: "2026-01-01T00:00:00Z"}}
initial_state: {initial}
{resources}subflows:
{subflows}
steps:
{steps}
'''


FLOW = scenario('''  - {id: before, write: {order: {$literal: before}}, transition: invoke}
  - id: invoke
    call: {subflow: child, with: {value: {$literal: scoped}}}
    transition: after
  - {id: after, write: {done: {$literal: true}}, transition: null}''', '''  child:
    steps:
      - {id: child_step, write: {seen: {$scope: value}}, transition: null}''')


REPEAT = scenario('''  - id: loop
    repeat: {count: {$literal: 3}, max: 3, subflow: body, index_as: i}
    transition: after
  - {id: after, write: {done: {$literal: true}}, transition: null}''', '''  body:
    steps:
      - id: body_step
        write: {values: {$append: {list: {$state: values}, value: {$scope: i}}}}
        transition: null''', "{values: []}")


def run(text=FLOW, inputs=None):
    return run_scenario(compile_document(parse_yaml(text)), "seed", inputs=inputs)


class Phase04ControlFlowTests(unittest.TestCase):
    def test_call_invokes_subflow_and_returns_to_outer_sequence(self):
        r = run(); self.assertEqual([x.address.step_id for x in r.history.records], ["before", "child_step", "after"])

    def test_same_subflow_called_from_distinct_sites_has_distinct_execution_addresses(self):
        text = scenario('''  - {id: a, call: {subflow: child}, transition: b}
  - {id: b, call: {subflow: child}, transition: null}''', '''  child:
    steps: [{id: inner, write: {x: {$literal: 1}}, transition: null}]''')
        records = run(text).history.records; self.assertNotEqual(records[0].address.subflow_invocations, records[1].address.subflow_invocations)

    def test_subflow_scope_values_are_explicit_and_do_not_leak(self):
        r = run(); self.assertEqual(r.final_state["seen"], "scoped"); self.assertNotIn("value", r.final_state)

    def test_nested_subflow_scope_requires_explicit_forwarding(self):
        nested = scenario('''  - {id: outer_call, call: {subflow: outer, with: {x: {$literal: "yes"}}}, transition: null}''', '''  outer:
    steps: [{id: inner_call, call: {subflow: inner}, transition: null}]
  inner:
    steps: [{id: inner_step, write: {seen: {$scope: x}}, transition: null}]''')
        with self.assertRaises(ScopeResolutionError): run(nested)
        forwarded = nested.replace("call: {subflow: inner}", "call: {subflow: inner, with: {x: {$scope: x}}}")
        self.assertEqual(run(forwarded).final_state["seen"], "yes")

    def test_child_scope_shadowing_does_not_mutate_parent_scope(self):
        text = scenario('''  - {id: start, call: {subflow: outer, with: {x: {$literal: parent}}}, transition: null}''', '''  outer:
    steps:
      - {id: shadow, call: {subflow: inner, with: {x: {$literal: child}}}, transition: observe}
      - {id: observe, write: {parent: {$scope: x}}, transition: null}
  inner:
    steps: [{id: child_observe, write: {child: {$scope: x}}, transition: null}]''')
        r = run(text); self.assertEqual((r.final_state["parent"], r.final_state["child"]), ("parent", "child"))

    def test_unknown_subflow_is_rejected_before_execution(self):
        with self.assertRaises(UnknownSubflowError): compile_document(parse_yaml(FLOW.replace("subflow: child", "subflow: absent", 1)))

    def test_subflow_call_cycle_is_rejected_before_execution(self):
        text = scenario('''  - {id: start, call: {subflow: a}, transition: null}''', '''  a:
    steps: [{id: call_b, call: {subflow: b}, transition: null}]
  b:
    steps: [{id: call_a, call: {subflow: a}, transition: null}]''')
        with self.assertRaises(SubflowCycleError): compile_document(parse_yaml(text))

    def test_branch_selects_first_true_case(self):
        text = scenario('''  - id: choose
    branch:
      cases:
        - {when: {$literal: true}, subflow: first}
        - {when: {$literal: true}, subflow: second}
    transition: null''', '''  first:
    steps: [{id: first_step, write: {chosen: {$literal: first}}, transition: null}]
  second:
    steps: [{id: second_step, write: {chosen: {$literal: second}}, transition: null}]''')
        self.assertEqual(run(text).final_state["chosen"], "first")

    def test_branch_else_runs_when_no_case_matches(self):
        text = self._branch(False); self.assertEqual(run(text).final_state["chosen"], "else")

    def _branch(self, value):
        literal = "true" if value else "false"
        return scenario(f'''  - id: choose
    branch:
      cases: [{{when: {{$literal: {literal}}}, subflow: selected}}]
      else: {{subflow: fallback}}
    transition: null''', '''  selected:
    steps: [{id: selected_step, write: {chosen: {$literal: selected}}, transition: null}]
  fallback:
    steps: [{id: fallback_step, write: {chosen: {$literal: else}}, transition: null}]''')

    def test_branch_condition_requires_boolean(self):
        with self.assertRaises(BranchConditionError): run(self._branch(False).replace("$literal: false", "$literal: 1"))

    def test_branch_not_taken_does_not_shift_taken_path_determinism(self):
        base = self._branch(True); extra = base.replace("cases: [", "cases: [{when: {$literal: false}, subflow: fallback}, ")
        self.assertEqual(run(base).final_state, run(extra).final_state)

    def test_repeat_runs_exact_bounded_count(self):
        self.assertEqual(run(REPEAT).final_state["values"], [0, 1, 2])

    def test_repeat_zero_count_executes_no_body(self):
        r = run(REPEAT.replace("$literal: 3", "$literal: 0", 1)); self.assertEqual(r.final_state["values"], []); self.assertEqual(len(r.history.records), 1)

    def test_repeat_rejects_count_above_declared_max_before_execution(self):
        with self.assertRaises(RepeatLimitError): run(REPEAT.replace("$literal: 3", "$literal: 4", 1))

    def test_repeat_rejects_negative_noninteger_and_boolean_counts(self):
        for value in ("-1", "{$decimal: '1.5'}", "true"):
            with self.subTest(value=value), self.assertRaises(RepeatCountError): run(REPEAT.replace("$literal: 3", f"$literal: {value}", 1))

    def test_repeat_index_is_available_only_in_iteration_scope(self):
        self.assertEqual(run(REPEAT).final_state["values"], [0, 1, 2]); self.assertNotIn("i", run(REPEAT).final_state)

    def test_repeated_iterations_have_distinct_execution_addresses(self):
        records = run(REPEAT).history.records[:3]; self.assertEqual([r.address.repetition_indexes for r in records], [(0,), (1,), (2,)])

    def test_repeat_same_context_replays_exactly(self):
        r = run(REPEAT); self.assertEqual(r.to_json(), replay_scenario(REPEAT, r.manifest).to_json())

    def test_subflow_failure_preserves_failing_step_atomicity(self):
        bad = REPEAT.replace("value: {$scope: i}", "value: {$state: missing}")
        with self.assertRaises(ScopeResolutionError): run(bad)

    def test_control_flow_canonical_hash_ignores_subflow_mapping_order(self):
        text = self._branch(True)
        start = text.index("  selected:"); middle = text.index("  fallback:"); end = text.index("steps:\n", middle)
        reordered = text[:start] + text[middle:end] + text[start:middle] + text[end:]
        self.assertEqual(canonical_scenario_hash(text), canonical_scenario_hash(reordered))

    def test_control_flow_canonical_hash_preserves_case_and_step_order(self):
        text = self._branch(True); self.assertNotEqual(canonical_scenario_hash(text), canonical_scenario_hash(text.replace("selected", "changed", 1)))
        self.assertNotEqual(canonical_scenario_hash(FLOW), canonical_scenario_hash(FLOW.replace("id: before", "id: before_changed")))

    def test_control_flow_replay_is_exact(self):
        text = Path("examples/phase0_4_control_flow.yaml").read_text(); inputs = {"premium": True, "retry_count": 2, "customer_id": "c"}; r = run(text, inputs); self.assertEqual(r.normalized(), replay_scenario(text, r.manifest, inputs=inputs).normalized())

    def test_resource_and_scope_values_compose_inside_subflow(self):
        text = FLOW.replace("$literal: scoped", "$resource: data.value").replace("subflows:", "resources:\n  data: {value: {$literal: exact}}\nsubflows:"); self.assertEqual(run(text).final_state["seen"], "exact")

    def test_unrelated_control_node_does_not_shift_existing_generated_values(self):
        text = Path("examples/phase0_4_control_flow.yaml").read_text(); inputs = {"premium": True, "retry_count": 2, "customer_id": "c"}; a = run(text, inputs); b = run(text.replace("cases:\n", "cases:\n        - {when: {$literal: false}, subflow: standard_treatment}\n"), inputs); self.assertEqual(a.final_state["attempts"], b.final_state["attempts"])

    def test_pytest_harness_runs_branch_subflow_repeat_scenario(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test_real.py"; path.write_text('''from pathlib import Path\npytest_plugins=["scenario_engine.pytest_plugin"]\ndef test_flow(scenario_engine):\n t=Path("examples/phase0_4_control_flow.yaml").read_text(); i={"premium":True,"retry_count":2,"customer_id":"c"}; r=scenario_engine.run_text(t,root_seed="s",inputs=i); assert r.to_json()==scenario_engine.replay_text(t,r.manifest,inputs=i).to_json()\n''')
            completed = subprocess.run([sys.executable, "-m", "pytest", "-q", str(path)], capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_phase0_4_example_and_all_prior_examples_remain_compatible(self):
        cases = [("examples/phase0_1b_cart.yaml", None), ("examples/phase0_3_resources.yaml", {"customer_id": "c", "maximum_quantity": 5}), ("examples/phase0_4_control_flow.yaml", {"premium": False, "retry_count": 1, "customer_id": "c"})]
        for path, inputs in cases:
            text = Path(path).read_text(); r = run(text, inputs); self.assertEqual(r.to_json(), replay_scenario(text, r.manifest, inputs=inputs).to_json())


if __name__ == "__main__": unittest.main()
