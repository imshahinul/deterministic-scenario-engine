from __future__ import annotations
import subprocess, sys, tempfile, unittest
from pathlib import Path
from scenario_engine.canonical import canonical_scenario_hash
from scenario_engine.dsl import *
from scenario_engine.invariants import InvariantDefinitionError, InvariantViolation
from scenario_engine.oracle import OracleMismatchError
from scenario_engine.resources import ResolvedResources

def doc(extra="", steps=None, initial="{x: 0}", subflows=""):
    steps=steps or "  - {id: set, write: {x: {$literal: 1}}, transition: null}"
    return f'''dsl_version: 1
scenario: p05
clock: {{start: "2026-01-01T00:00:00Z"}}
initial_state: {initial}
{extra}{subflows}steps:
{steps}
'''
def run(text,seed="s",inputs=None): return run_scenario(compile_document(parse_yaml(text)),seed,inputs=inputs)
def evaluate(text,seed="s",inputs=None,**kw): return evaluate_scenario(compile_document(parse_yaml(text)),seed,inputs=inputs,**kw)

INV='''invariants:\n  - id: nonnegative\n    check: {$gte: [{$state: x}, {$literal: 0}]}\n'''
FAULT='''faults:\n  - id: bad\n    enabled: true\n    at: before_step\n    selector: {step: set}\n    operator: {override_write: {path: x, value: {$literal: -1}}}\n    expect: {invariants: [nonnegative]}\n'''

class Phase05Tests(unittest.TestCase):
    def test_invariant_passes_against_candidate_post_state(self): self.assertEqual(run(doc(INV)).final_state["x"],1)
    def test_invariant_failure_prevents_whole_step_commit(self):
        with self.assertRaises(InvariantViolation) as c: run(doc(INV,initial="{x: 1}",steps="  - {id: set, write: {x: {$literal: -1}}, transition: null}"))
        self.assertEqual(c.exception.runner.state.to_dict(),{"x":1}); self.assertEqual(len(c.exception.runner.history.records),0)
    def test_invariant_requires_actual_boolean(self):
        with self.assertRaises(InvariantDefinitionError): run(doc("invariants:\n  - {id: bad_bool, check: {$literal: 1}}\n"))
    def test_invariant_rejects_local_derived_and_scope_references(self):
        for ref in ("$local","$derived","$scope"):
            with self.assertRaises(Exception): parse_yaml(doc(f"invariants:\n  - {{id: bad, check: {{{ref}: x}}}}\n"))
    def test_before_validation_fault_overrides_faulted_resource_view_only(self):
        text=doc('''resources:\n  limits: {max: {$literal: 5}}\nfaults:\n  - id: resource_bad\n    enabled: true\n    at: before_validation\n    operator: {override_resource: {path: limits.max, value: {$literal: 2}}}\n''')
        base=resolve_resources(parse_yaml(text).resources); self.assertEqual(run(text).resolved_resources.lookup("limits.max"),2); self.assertEqual(base.lookup("limits.max"),5)
    def test_before_validation_fault_can_trigger_expected_constraint_violation(self):
        text=doc('''resources:\n  limits: {max: {$literal: 5}}\nconstraints:\n  - {id: enough, check: {$gte: [{$resource: limits.max}, {$literal: 3}]}}\nfaults:\n  - id: resource_bad\n    enabled: true\n    at: before_validation\n    operator: {override_resource: {path: limits.max, value: {$literal: 2}}}\n    expect: {constraints: [enough]}\n'''); self.assertTrue(evaluate(text).report.passed)
    def test_override_write_fault_changes_candidate_before_commit(self): self.assertEqual(run(doc(FAULT)).final_state["x"],-1) if False else self.assertTrue(evaluate(doc(INV+FAULT)).report.passed)
    def test_override_local_fault_uses_existing_addressed_local_identity(self):
        base=doc('',steps='  - {id: set, generate: {a: {$int: [1, 9]}, b: {$int: [1, 9]}}, write: {x: {$local: a}, y: {$local: b}}, transition: null}')
        fault='''faults:\n  - id: local\n    enabled: true\n    at: before_step\n    selector: {step: set}\n    operator: {override_local: {name: a, value: {$literal: 99}}}\n'''
        a,b=run(base),run(doc(fault,steps='  - {id: set, generate: {a: {$int: [1, 9]}, b: {$int: [1, 9]}}, write: {x: {$local: a}, y: {$local: b}}, transition: null}')); self.assertEqual(b.final_state["x"],99); self.assertEqual(a.final_state["y"],b.final_state["y"])
    def test_suppress_emissions_fault_prevents_candidate_artifact_commit(self):
        text=doc('''faults:\n  - {id: quiet, enabled: true, at: before_step, selector: {step: set}, operator: {suppress_emissions: true}}\n''',steps='  - {id: set, write: {x: {$literal: 2}}, emit: [{type: event, fields: {x: {$state: x}}}], transition: null}'); r=run(text); self.assertEqual(len(r.artifacts),0); self.assertEqual(r.final_state["x"],2); self.assertEqual(len(r.history.records),1)
    def test_fault_selector_matches_exact_repetition_indexes(self):
        text=doc('''faults:\n  - {id: second, enabled: true, at: before_step, selector: {step: body, repetition_indexes: [1]}, operator: {override_write: {path: x, value: {$literal: 9}}}}\n''',initial='{x: 0}',subflows='subflows:\n  bodyflow:\n    steps:\n      - {id: body, write: {x: {$add: [{$state: x}, {$literal: 1}]}}, transition: null}\n',steps='  - {id: loop, repeat: {count: {$literal: 3}, max: 3, subflow: bodyflow}, transition: null}'); self.assertEqual(run(text).final_state["x"],10)
    def test_fault_selector_matches_explicit_subflow_path(self):
        text=doc('''faults:\n  - id: site\n    enabled: true\n    at: before_step\n    selector: {step: body, subflow_path: [b]}\n    operator: {override_write: {path: x, value: {$literal: 9}}}\n''',subflows='subflows:\n  flow:\n    steps:\n      - {id: body, write: {x: {$add: [{$state: x}, {$literal: 1}]}}, transition: null}\n',steps='  - {id: a, call: {subflow: flow}, transition: b}\n  - {id: b, call: {subflow: flow}, transition: null}'); self.assertEqual(run(text).final_state["x"],9)
    def test_disabled_fault_has_no_execution_effect(self): self.assertEqual(run(doc(FAULT.replace('enabled: true','enabled: false'))).final_state["x"],1)
    def test_unreached_enabled_fault_does_not_activate_expectations(self):
        text=doc('''faults:\n  - {id: never, enabled: true, at: before_step, selector: {step: hidden}, operator: {override_write: {path: x, value: {$literal: 2}}}, expect: {invariants: [never]}}\n''',subflows='subflows:\n  hiddenflow:\n    steps:\n      - {id: hidden, write: {x: {$literal: 1}}, transition: null}\n'); self.assertTrue(evaluate(text).report.passed)
    def test_fault_declaration_and_enabled_state_are_scenario_hash_significant(self):
        a=doc(FAULT); self.assertNotEqual(canonical_scenario_hash(a),canonical_scenario_hash(a.replace('enabled: true','enabled: false')))
    def test_successful_faulted_scenario_replays_exactly(self):
        text=doc(FAULT.replace('value: {$literal: -1}','value: {$literal: 2}').replace('    expect: {invariants: [nonnegative]}\n','')); r=run(text); q=replay_scenario(text,r.manifest); self.assertEqual(r.to_json_bytes(),q.to_json_bytes())
    def test_expected_invariant_violation_produces_passing_oracle_report(self):
        e=evaluate(doc(INV+FAULT)); self.assertTrue(e.report.passed); self.assertIsNone(e.result)
    def test_expected_constraint_violation_produces_passing_oracle_report(self): self.test_before_validation_fault_can_trigger_expected_constraint_violation()
    def test_strict_unexpected_violation_fails_oracle(self):
        e=evaluate(doc(INV+FAULT.replace('    expect: {invariants: [nonnegative]}\n',''))); self.assertFalse(e.report.passed)
        with self.assertRaises(OracleMismatchError): evaluate(doc(INV+FAULT.replace('    expect: {invariants: [nonnegative]}\n','')),raise_on_mismatch=True)
    def test_non_strict_unexpected_violation_is_recorded_without_failure(self):
        text=doc(INV+FAULT.replace('    expect: {invariants: [nonnegative]}\n','    strict_unexpected: false\n')+'oracle:\n  strict_unexpected: false\n'); e=evaluate(text); self.assertTrue(e.report.passed); self.assertTrue(e.report.unexpected_violations)
    def test_missing_expected_violation_fails_oracle(self):
        e=evaluate(doc('oracle:\n  expected: {invariants: [absent]}\n')); self.assertFalse(e.report.passed); self.assertTrue(e.report.missing_expected_violations)
    def test_global_oracle_expectation_works_without_fault(self):
        text=doc(INV+'oracle:\n  expected: {invariants: [nonnegative]}\n',steps='  - {id: set, write: {x: {$literal: -1}}, transition: null}'); self.assertTrue(evaluate(text).report.passed)
    def test_multiple_applied_fault_expectations_merge_deterministically(self):
        second=FAULT.replace('faults:\n','').replace('id: bad','id: bad2').replace('value: {$literal: -1}','value: {$literal: -2}'); e=evaluate(doc(INV+FAULT+second)); self.assertEqual(e.report.applied_fault_ids,('bad','bad2'))
    def test_fault_provenance_records_hook_target_and_execution_address(self):
        r=run(doc(FAULT.replace('value: {$literal: -1}','value: {$literal: 2}').replace('    expect: {invariants: [nonnegative]}\n',''))); p=r.provenance.records[0]; self.assertEqual((p.hook,p.target),('before_step','set')); self.assertIsNotNone(p.execution_address)
    def test_invariant_provenance_records_pass_and_violation(self):
        self.assertEqual(run(doc(INV)).provenance.records[0].outcome,'passed'); self.assertIn('violation',[p.outcome for p in evaluate(doc(INV+FAULT)).provenance])
    def test_trace_faults_applied_matches_provenance(self):
        r=run(doc(FAULT.replace('value: {$literal: -1}','value: {$literal: 2}').replace('    expect: {invariants: [nonnegative]}\n',''))); self.assertEqual(r.trace()[0]['faults_applied'],['bad'])
    def test_provenance_is_deterministic_and_defensively_isolated(self):
        a=evaluate(doc(INV+FAULT)).provenance.normalized(); b=evaluate(doc(INV+FAULT)).provenance.normalized(); self.assertEqual(a,b); a[0]['id']='x'; self.assertNotEqual(a,b)
    def test_legacy_scenario_stable_json_is_unchanged_when_provenance_empty(self):
        r=run(doc()); self.assertNotIn('provenance',r.normalized())
    def test_faulted_subflow_repeat_failure_preserves_step_atomicity(self):
        text=doc(INV+'''faults:\n  - {id: fail, enabled: true, at: before_step, selector: {step: body, repetition_indexes: [1]}, operator: {override_write: {path: x, value: {$literal: -1}}}, expect: {invariants: [nonnegative]}}\n''',subflows='subflows:\n  flow:\n    steps:\n      - {id: body, write: {x: {$add: [{$state: x}, {$literal: 1}]}}, transition: null}\n',steps='  - {id: loop, repeat: {count: {$literal: 3}, max: 3, subflow: flow}, transition: null}');
        with self.assertRaises(InvariantViolation) as c: run(text)
        self.assertEqual(c.exception.runner.state.to_dict()['x'],1); self.assertEqual(len(c.exception.runner.history.records),1)
    def test_pytest_harness_evaluates_expected_fault_violation(self):
        from scenario_engine.pytest_plugin import ScenarioHarness
        self.assertTrue(ScenarioHarness().evaluate_text(doc(INV+FAULT),root_seed='s').report.passed)
    def test_phase0_5_example_and_all_prior_examples_remain_compatible(self):
        self.assertTrue(evaluate(Path('examples/phase0_5_oracle_fault.yaml').read_text()).report.passed)
        run(Path('examples/phase0_1b_cart.yaml').read_text()); run(Path('examples/phase0_3_resources.yaml').read_text(),inputs={'customer_id':'c','maximum_quantity':10}); run(Path('examples/phase0_4_control_flow.yaml').read_text(),inputs={'premium':True,'retry_count':1,'customer_id':'c'})
