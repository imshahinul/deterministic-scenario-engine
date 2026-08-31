from __future__ import annotations
from types import MappingProxyType

from scenario_engine.address import ExecutionAddress
from scenario_engine.canonical import canonical_scenario_hash
from scenario_engine.clock import LogicalClock
from scenario_engine.ids import ID_VERSION
from scenario_engine.manifest import ENGINE_VERSION, GENERATOR_VERSIONS, ReplayCompatibilityError, ReproducibilityManifest
from scenario_engine.result import ScenarioResult
from scenario_engine.rng import RNG_VERSION
from scenario_engine.resources import resolve_resources
from scenario_engine.runner import ScenarioRunner
from scenario_engine.state import ScenarioState
from scenario_engine.provenance import ProvenanceRecord, ScenarioProvenance
from scenario_engine.invariants import InvariantViolation, evaluate_invariants
from scenario_engine.faults import apply_step_faults
from scenario_engine.oracle import OracleEvaluation, OracleMismatchError, OracleReport
from scenario_engine.validation import ConstraintDefinitionError, ConstraintViolation, ResourceValidationError, validate_resources
from scenario_engine.expressions import EvaluationEnvironment

from .compiler import compile_constraint, compile_document, compile_expression, compile_scoped_sequence
from .models import CompiledScenario
from .parser import parse_yaml


def _manifest(scenario, root_seed, run_index, locale, base_resources):
    return ReproducibilityManifest(root_seed=root_seed, scenario_canonical_hash=canonical_scenario_hash(scenario),
        engine_version=ENGINE_VERSION, dsl_version=scenario.document.dsl_version,
        generator_versions=GENERATOR_VERSIONS, rng_algorithm_version=RNG_VERSION,
        id_algorithm_version=ID_VERSION, locale=locale,
        reference_clock_start=scenario.reference_clock_start, run_index=run_index,
        input_resource_hashes=base_resources.hashes())


def _prepare(scenario, inputs, provenance):
    if scenario.resources is not None:
        if inputs is not None: raise ValueError("inputs must be supplied before compilation or to an unresolved scenario")
        base = scenario.resources
    else:
        base = resolve_resources(scenario.document.resources, inputs)
    resources = base
    applied=[]
    for fault in scenario.document.faults:
        if not fault["enabled"] or fault["at"] != "before_validation": continue
        body=fault["operator"]["override_resource"]
        value=compile_expression(body["value"],resources).evaluate(EvaluationEnvironment({}, {}, {}))
        resources=resources.with_override(body["path"],value); applied.append(fault)
        provenance.append(ProvenanceRecord("fault_application",fault["id"],hook="before_validation",target=body["path"],details=MappingProxyType({"operator":"override_resource"})))
    validate_resources(resources,scenario.document.validators)
    for item in scenario.document.constraints:
        result=compile_constraint(item["check"],resources).evaluate(EvaluationEnvironment({}, {}, {}))
        if type(result) is not bool: raise ConstraintDefinitionError(f"constraint {item['id']}: check must return boolean")
        if not result:
            provenance.append(ProvenanceRecord("constraint_violation",item["id"],outcome="violation"))
            error=ConstraintViolation(f"constraint {item['id']} violated" + (f": {item['message']}" if item.get("message") else ""))
            error.constraint_id=item["id"]; error.applied_faults=tuple(applied); error.provenance=ScenarioProvenance(tuple(provenance)); error.base_resources=base; error.resources=resources
            raise error
    return compile_document(scenario.document,resources),base,resources,applied


def _execute(scenario, root_seed, run_index, locale, inputs):
    if isinstance(run_index,bool) or not isinstance(run_index,int) or run_index<0: raise ValueError("run_index must be a nonnegative integer")
    records=[]
    try:
        scenario,base,resources,applied=_prepare(scenario,inputs,records)
    except ConstraintViolation as error:
        unresolved=scenario
        base=error.base_resources
        error.manifest=_manifest(unresolved,root_seed,run_index,locale,base)
        raise
    manifest=_manifest(scenario,root_seed,run_index,locale,base)
    runner=ScenarioRunner(root_seed,ExecutionAddress(scenario.scenario_id,run_index),ScenarioState(scenario.initial_state),LogicalClock(scenario.reference_clock_start))
    invariants=tuple((item["id"],compile_expression(item["check"],resources)) for item in scenario.document.invariants)

    def execute_invocation(control_id,target,bindings,scope,repetitions,path):
        from scenario_engine.control_flow import evaluate_bindings, invocation_component
        child_scope=evaluate_bindings(bindings,compile_expression,runner.state.snapshot(),resources,scope)
        old=runner.address; runner.address=runner.address.with_subflow_invocation(invocation_component(control_id,target))
        for index in repetitions: runner.address=runner.address.with_repetition(index)
        try: execute_sequence(compile_scoped_sequence(scenario.document.subflows[target],resources,child_scope),child_scope,path+(control_id,))
        finally: runner.address=old

    def execute_sequence(steps,scope=None,path=()):
        from scenario_engine.control_flow import BranchConditionError,evaluate_bindings,invocation_component,validate_repeat_count
        for node in steps:
            if hasattr(node,"spec"):
                spec,faults=apply_step_faults(node.spec,scenario.document.faults,runner.address,runner.state.snapshot(),resources,scope,path)
                for fault in faults:
                    op=next(iter(fault["operator"])); target=spec.step_id
                    records.append(ProvenanceRecord("fault_application",fault["id"],runner.address.for_step(spec.step_id).canonical(),spec.step_id,"before_step",target,details=MappingProxyType({"operator":op})))
                    applied.append(fault)
                def validator(candidate,address):
                    evaluate_invariants(invariants,candidate.post_state,spec.step_id,address,
                        lambda iid,outcome,addr,sid: records.append(ProvenanceRecord("invariant_check",iid,addr.canonical(),sid,outcome=outcome)))
                try: runner.run_step(spec,validator if invariants else None)
                except InvariantViolation as error:
                    applied.extend(fault for fault in faults if fault not in applied)
                    records.append(ProvenanceRecord("invariant_violation",error.invariant_id,error.execution_address,error.step_id,outcome="violation"))
                    error.runner=runner; error.applied_faults=tuple(applied); error.provenance=ScenarioProvenance(tuple(records)); error.manifest=manifest; error.resources=resources
                    raise
                continue
            state=runner.state.snapshot()
            if node.call is not None: execute_invocation(node.step_id,node.call["subflow"],node.call["with"],scope,(),path)
            elif node.branch is not None:
                selected=None; env=EvaluationEnvironment(state,{}, {},scope)
                for case in node.branch["cases"]:
                    condition=compile_expression(case["when"],resources).evaluate(env)
                    if type(condition) is not bool: raise BranchConditionError("branch condition must evaluate to boolean")
                    if condition: selected=case; break
                if selected is None: selected=node.branch.get("else")
                if selected is not None: execute_invocation(node.step_id,selected["subflow"],selected["with"],scope,(),path)
            else:
                repeat=node.repeat; env=EvaluationEnvironment(state,{}, {},scope)
                count=validate_repeat_count(compile_expression(repeat["count"],resources).evaluate(env),repeat["max"])
                for index in range(count):
                    bindings=dict(repeat["with"]); child=evaluate_bindings(bindings,compile_expression,runner.state.snapshot(),resources,scope)
                    if "index_as" in repeat: child=MappingProxyType({**dict(child),repeat["index_as"]:index})
                    old=runner.address; runner.address=runner.address.with_subflow_invocation(invocation_component(node.step_id,repeat["subflow"])).with_repetition(index)
                    try: execute_sequence(compile_scoped_sequence(scenario.document.subflows[repeat["subflow"]],resources,child),child,path+(node.step_id,))
                    finally: runner.address=old
    execute_sequence(scenario.steps)
    provenance=ScenarioProvenance(tuple(records))
    return ScenarioResult(scenario.scenario_id,runner,manifest,resources,provenance),tuple(applied),provenance


def run_scenario(scenario: CompiledScenario,root_seed,run_index=0,locale="C",inputs=None):
    return _execute(scenario,root_seed,run_index,locale,inputs)[0]


def evaluate_scenario(scenario: CompiledScenario,root_seed,run_index=0,locale="C",inputs=None,raise_on_mismatch=False):
    result=None; observed_c=(); observed_i=(); applied=(); provenance=ScenarioProvenance()
    try: result,applied,provenance=_execute(scenario,root_seed,run_index,locale,inputs); manifest=result.manifest
    except ConstraintViolation as error:
        observed_c=(error.constraint_id,); applied=error.applied_faults; provenance=error.provenance; manifest=error.manifest
    except InvariantViolation as error:
        observed_i=(error.invariant_id,); applied=error.applied_faults; provenance=error.provenance; manifest=error.manifest
    oracle=scenario.document.oracle or {"expected":{"constraints":(),"invariants":()},"strict_unexpected":True}
    expected_c=list(oracle["expected"]["constraints"]); expected_i=list(oracle["expected"]["invariants"])
    for fault in applied:
        for value in fault["expect"]["constraints"]:
            if value not in expected_c: expected_c.append(value)
        for value in fault["expect"]["invariants"]:
            if value not in expected_i: expected_i.append(value)
    unexpected=tuple([f"constraint:{x}" for x in observed_c if x not in expected_c]+[f"invariant:{x}" for x in observed_i if x not in expected_i])
    missing=tuple([f"constraint:{x}" for x in expected_c if x not in observed_c]+[f"invariant:{x}" for x in expected_i if x not in observed_i])
    strict=oracle["strict_unexpected"] or any(f["strict_unexpected"] for f in applied)
    report=OracleReport(observed_c,observed_i,tuple(expected_c),tuple(expected_i),unexpected,missing,tuple(f["id"] for f in applied),strict,not missing and (not strict or not unexpected))
    provenance=ScenarioProvenance(provenance.records+(ProvenanceRecord("oracle_evaluation","oracle",outcome="passed" if report.passed else "failed"),))
    evaluation=OracleEvaluation(manifest,result,report,provenance)
    if raise_on_mismatch and not report.passed: raise OracleMismatchError(evaluation)
    return evaluation


def replay_scenario(yaml_text,manifest,*,inputs=None):
    document=parse_yaml(yaml_text); scenario=compile_document(document)
    base=resolve_resources(document.resources,inputs)
    expected={"scenario_canonical_hash":canonical_scenario_hash(scenario),"engine_version":ENGINE_VERSION,"dsl_version":document.dsl_version,
        "rng_algorithm_version":RNG_VERSION,"id_algorithm_version":ID_VERSION,"generator_versions":GENERATOR_VERSIONS,"reference_clock_start":document.reference_clock_start}
    for field,current in expected.items():
        if getattr(manifest,field)!=current: raise ReplayCompatibilityError(f"{field} mismatch")
    if manifest.input_resource_hashes!=base.hashes(): raise ReplayCompatibilityError("input_resource_hashes mismatch")
    if manifest.domain_pack_versions: raise ReplayCompatibilityError("domain_pack_versions unsupported in Phase 0.2A")
    return run_scenario(scenario,manifest.root_seed,manifest.run_index,locale=manifest.locale,inputs=inputs)
