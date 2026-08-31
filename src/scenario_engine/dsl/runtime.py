from __future__ import annotations

from scenario_engine.address import ExecutionAddress
from scenario_engine.canonical import canonical_scenario_hash
from scenario_engine.clock import LogicalClock
from scenario_engine.ids import ID_VERSION
from scenario_engine.manifest import (
    ENGINE_VERSION, GENERATOR_VERSIONS, ReplayCompatibilityError,
    ReproducibilityManifest,
)
from scenario_engine.result import ScenarioResult
from scenario_engine.rng import RNG_VERSION
from scenario_engine.resources import ResolvedResources, resolve_resources
from scenario_engine.runner import ScenarioRunner
from scenario_engine.state import ScenarioState

from .compiler import compile_constraint, compile_document, compile_expression, compile_scoped_sequence
from .errors import DSLCompilationError
from .models import CompiledScenario
from .parser import parse_yaml


def run_scenario(
    scenario: CompiledScenario,
    root_seed: str | int,
    run_index: int = 0,
    locale: str = "C",
    inputs=None,
) -> ScenarioResult:
    if isinstance(run_index, bool) or not isinstance(run_index, int) or run_index < 0:
        raise ValueError("run_index must be a nonnegative integer")
    resources = scenario.resources
    if resources is None:
        resources = resolve_resources(scenario.document.resources, inputs)
        from scenario_engine.validation import evaluate_constraints, validate_resources
        validate_resources(resources, scenario.document.validators)
        constraints = tuple((item["id"], compile_constraint(item["check"], resources), item.get("message"))
                            for item in scenario.document.constraints)
        evaluate_constraints(constraints)
        scenario = compile_document(scenario.document, resources)
    elif inputs is not None:
        raise ValueError("inputs must be supplied before compilation or to an unresolved scenario")
    runner = ScenarioRunner(
        root_seed,
        ExecutionAddress(scenario.scenario_id, run_index),
        ScenarioState(scenario.initial_state),
        LogicalClock(scenario.reference_clock_start),
    )
    from types import MappingProxyType
    from scenario_engine.control_flow import (BranchConditionError, evaluate_bindings,
        invocation_component, validate_repeat_count)
    from scenario_engine.expressions import EvaluationEnvironment

    def execute_invocation(control_id, target, bindings, scope, repetitions):
        child_scope = evaluate_bindings(bindings, compile_expression, runner.state.snapshot(), resources, scope)
        old_address = runner.address
        runner.address = runner.address.with_subflow_invocation(invocation_component(control_id, target))
        for index in repetitions: runner.address = runner.address.with_repetition(index)
        child_steps = compile_scoped_sequence(scenario.document.subflows[target], resources, child_scope)
        try: execute_sequence(child_steps, child_scope)
        finally: runner.address = old_address

    def execute_sequence(steps, scope=None):
        for node in steps:
            if hasattr(node, "spec"):
                runner.run_step(node.spec)
                continue
            state = runner.state.snapshot()
            if node.call is not None:
                execute_invocation(node.step_id, node.call["subflow"], node.call["with"], scope, ())
            elif node.branch is not None:
                selected = None
                env = EvaluationEnvironment(state, MappingProxyType({}), MappingProxyType({}), scope)
                for case in node.branch["cases"]:
                    condition = compile_expression(case["when"], resources).evaluate(env)
                    if type(condition) is not bool: raise BranchConditionError("branch condition must evaluate to boolean")
                    if condition: selected = case; break
                if selected is None: selected = node.branch.get("else")
                if selected is not None: execute_invocation(node.step_id, selected["subflow"], selected["with"], scope, ())
            else:
                repeat = node.repeat
                env = EvaluationEnvironment(state, MappingProxyType({}), MappingProxyType({}), scope)
                count = validate_repeat_count(compile_expression(repeat["count"], resources).evaluate(env), repeat["max"])
                for index in range(count):
                    bindings = dict(repeat["with"])
                    child_scope = evaluate_bindings(bindings, compile_expression, runner.state.snapshot(), resources, scope)
                    if "index_as" in repeat:
                        child_scope = MappingProxyType({**dict(child_scope), repeat["index_as"]: index})
                    old_address = runner.address
                    runner.address = runner.address.with_subflow_invocation(invocation_component(node.step_id, repeat["subflow"])).with_repetition(index)
                    child_steps = compile_scoped_sequence(scenario.document.subflows[repeat["subflow"]], resources, child_scope)
                    try: execute_sequence(child_steps, child_scope)
                    finally: runner.address = old_address
    execute_sequence(scenario.steps)
    manifest = ReproducibilityManifest(
        root_seed=root_seed,
        scenario_canonical_hash=canonical_scenario_hash(scenario),
        engine_version=ENGINE_VERSION,
        dsl_version=scenario.document.dsl_version,
        generator_versions=GENERATOR_VERSIONS,
        rng_algorithm_version=RNG_VERSION,
        id_algorithm_version=ID_VERSION,
        locale=locale,
        reference_clock_start=scenario.reference_clock_start,
        run_index=run_index,
        input_resource_hashes=resources.hashes(),
    )
    return ScenarioResult(scenario.scenario_id, runner, manifest, resources)


def replay_scenario(yaml_text: str, manifest: ReproducibilityManifest, *, inputs=None) -> ScenarioResult:
    document = parse_yaml(yaml_text)
    resources = resolve_resources(document.resources, inputs)
    from scenario_engine.validation import evaluate_constraints, validate_resources
    validate_resources(resources, document.validators)
    constraints = tuple((item["id"], compile_constraint(item["check"], resources), item.get("message"))
                        for item in document.constraints)
    evaluate_constraints(constraints)
    scenario = compile_document(document, resources)
    expected = {
        "scenario_canonical_hash": canonical_scenario_hash(scenario),
        "engine_version": ENGINE_VERSION,
        "dsl_version": scenario.document.dsl_version,
        "rng_algorithm_version": RNG_VERSION,
        "id_algorithm_version": ID_VERSION,
        "generator_versions": GENERATOR_VERSIONS,
        "reference_clock_start": scenario.reference_clock_start,
    }
    for field_name, current in expected.items():
        if getattr(manifest, field_name) != current:
            raise ReplayCompatibilityError(f"{field_name} mismatch")
    if manifest.input_resource_hashes != resources.hashes():
        raise ReplayCompatibilityError("input_resource_hashes mismatch")
    if manifest.domain_pack_versions:
        raise ReplayCompatibilityError("domain_pack_versions unsupported in Phase 0.2A")
    return run_scenario(
        scenario, manifest.root_seed, manifest.run_index, locale=manifest.locale,
    )
