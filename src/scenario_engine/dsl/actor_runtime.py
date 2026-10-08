"""Internal Phase 5.3 deterministic actor execution coordinator.

This module is deliberately not exported from :mod:`scenario_engine.dsl` and
does not construct a public result, manifest, or schedule artifact.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from types import MappingProxyType
from typing import Any, Mapping

from scenario_engine.address import ExecutionAddress
from scenario_engine.canonical import canonical_scenario_hash
from scenario_engine.clock import LogicalClock
from scenario_engine.control_flow import evaluate_bindings, validate_repeat_count
from scenario_engine.diagnostics import HumanDiagnostic
from scenario_engine.errors import ScenarioEngineError
from scenario_engine.expressions import EvaluationEnvironment
from scenario_engine.faults import apply_step_faults
from scenario_engine.invariants import evaluate_invariants
from scenario_engine.plugins import EMPTY_PLUGIN_REGISTRY, PluginRegistry
from scenario_engine.resources import resolve_resources
from scenario_engine.runner import ScenarioRunner
from scenario_engine.scheduler import MAX_SCHEDULER_SELECTIONS, SchedulerDecision, SchedulerInput, select_actor
from scenario_engine.state import ScenarioState
from scenario_engine.validation import ConstraintDefinitionError, ConstraintViolation, validate_resources

from .compiler import _compile_step, compile_constraint, compile_expression
from .models import ActorDocument, CompiledScenarioV2, StepDocument


MAX_CONTROL_ROUTING_OPERATIONS_PER_SELECTION = 4096


class ActorExecutionError(ScenarioEngineError, ValueError):
    """Internal deterministic actor execution failure."""

    code = "ACTOR_EXECUTION_INVALID"
    category = "ACTOR_EXECUTION"

    def __init__(self, message: str, *, code: str | None = None, limit: str | None = None) -> None:
        if code is not None:
            self.code = code
        self.limit = limit
        self.human_diagnostic = HumanDiagnostic(
            self.code, self.category, message,
            expected=(f"value at or below {limit}" if limit else None),
            remediation="correct the validated actor control state or reduce bounded execution work",
            details=({"limit": limit} if limit else None),
        )
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class _SequenceFrame:
    steps: tuple[StepDocument, ...]
    index: int
    scope: Mapping[str, Any] | None
    subflows: Mapping[str, tuple[StepDocument, ...]]
    invocations: tuple[int, ...] = ()
    repetitions: tuple[int, ...] = ()
    control_path: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _RepeatFrame:
    node: StepDocument
    next_index: int
    count: int
    scope: Mapping[str, Any] | None
    subflows: Mapping[str, tuple[StepDocument, ...]]
    invocations: tuple[int, ...]
    repetitions: tuple[int, ...]
    control_path: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _ActorControl:
    actor: ActorDocument
    frames: tuple[_SequenceFrame | _RepeatFrame, ...]


@dataclass(frozen=True, slots=True)
class ActorControlState:
    actor_address: str
    next_step_address: str | None
    terminal: bool


@dataclass(frozen=True, slots=True)
class ActorSchedulingDecision:
    ordinal: int
    selected_actor: str
    selected_step: str
    ready_actors: tuple[str, ...]
    scheduler_digest: str
    committed_history_length: int
    logical_clock: datetime
    outcome: str = "COMMITTED"


@dataclass(frozen=True, slots=True)
class ActorExecutionOutcome:
    """Small immutable, internal-only observation of actor execution."""

    final_state: Mapping[str, Any]
    final_logical_clock: datetime
    committed_history: tuple[Any, ...]
    actor_states: tuple[ActorControlState, ...]
    scheduling_decisions: tuple[ActorSchedulingDecision, ...]
    artifacts: tuple[Any, ...]
    classification: str
    schedule: Any = None


@dataclass(frozen=True, slots=True)
class _Routed:
    control: _ActorControl
    step: Any | None
    step_address: str | None
    operations: int
    invocations: tuple[int, ...] = ()
    repetitions: tuple[int, ...] = ()
    control_path: tuple[str, ...] = ()
    scope: Mapping[str, Any] | None = None


def _tick(count: int) -> int:
    if count >= MAX_CONTROL_ROUTING_OPERATIONS_PER_SELECTION:
        raise ActorExecutionError(
            "control routing operation limit exceeded before transition execution",
            code="ACTOR_CONTROL_ROUTING_LIMIT_EXCEEDED",
            limit="MAX_CONTROL_ROUTING_OPERATIONS_PER_SELECTION",
        )
    return count + 1


def _replace_top(frames, frame):
    return frames[:-1] + (frame,)


def _route(control: _ActorControl, state: Mapping[str, Any], resources, plugins, runner_state) -> _Routed:
    """Purely resolve one actor to its next whole executable transition."""
    from scenario_engine.control_flow import invocation_component

    frames = control.frames
    operations = 0
    while frames:
        top = frames[-1]
        if isinstance(top, _RepeatFrame):
            if top.next_index >= top.count:
                frames = frames[:-1]
                continue
            operations = _tick(operations)  # advance one repeat iteration
            repeat = top.node.repeat
            assert repeat is not None
            child_scope = evaluate_bindings(repeat["with"], compile_expression, state, resources, top.scope)
            if "index_as" in repeat:
                child_scope = MappingProxyType({**dict(child_scope), repeat["index_as"]: top.next_index})
            advanced = replace(top, next_index=top.next_index + 1)
            invocation = invocation_component(top.node.step_id, repeat["subflow"])
            operations = _tick(operations)  # enter the subflow invocation
            child = _SequenceFrame(
                top.subflows[repeat["subflow"]], 0, child_scope, top.subflows,
                top.invocations + (invocation,), top.repetitions + (top.next_index,),
                top.control_path + (top.node.step_id,),
            )
            frames = _replace_top(frames, advanced) + (child,)
            continue
        if top.index >= len(top.steps):
            frames = frames[:-1]
            continue
        operations = _tick(operations)  # inspect one flow node
        node = top.steps[top.index]
        advanced = replace(top, index=top.index + 1)
        frames = _replace_top(frames, advanced)
        if node.control_kind is None:
            compiled = _compile_step(node, resources, top.scope, plugins, runner_state)
            from scenario_engine.diagnostics import semantic_address
            step_address = semantic_address(
                ("actor", control.actor.actor_id), ("step", node.step_id), activate_actor=True,
            )
            if step_address is None:
                raise ActorExecutionError("validated actor step address became invalid")
            return _Routed(
                replace(control, frames=frames), compiled, step_address, operations,
                top.invocations, top.repetitions, top.control_path, top.scope,
            )
        if node.call is not None:
            operations = _tick(operations)  # enter a subflow invocation
            call = node.call
            scope = evaluate_bindings(call["with"], compile_expression, state, resources, top.scope)
            child = _SequenceFrame(
                top.subflows[call["subflow"]], 0, scope, top.subflows,
                top.invocations + (invocation_component(node.step_id, call["subflow"]),),
                top.repetitions, top.control_path + (node.step_id,),
            )
            frames += (child,)
        elif node.branch is not None:
            selected = None
            environment = EvaluationEnvironment(state, {}, {}, top.scope)
            for case in node.branch["cases"]:
                operations = _tick(operations)  # evaluate one ordered branch condition
                result = compile_expression(case["when"], resources).evaluate(environment)
                if type(result) is not bool:
                    from scenario_engine.control_flow import BranchConditionError
                    raise BranchConditionError("branch condition must evaluate to boolean")
                if result:
                    selected = case
                    break
            if selected is None:
                selected = node.branch.get("else")
            if selected is not None:
                operations = _tick(operations)  # enter selected subflow invocation
                scope = evaluate_bindings(selected["with"], compile_expression, state, resources, top.scope)
                child = _SequenceFrame(
                    top.subflows[selected["subflow"]], 0, scope, top.subflows,
                    top.invocations + (invocation_component(node.step_id, selected["subflow"]),),
                    top.repetitions, top.control_path + (node.step_id,),
                )
                frames += (child,)
        else:
            repeat = node.repeat
            assert repeat is not None
            environment = EvaluationEnvironment(state, {}, {}, top.scope)
            count = validate_repeat_count(compile_expression(repeat["count"], resources).evaluate(environment), repeat["max"])
            operations = _tick(operations)  # initiate repeat routing
            frames += (_RepeatFrame(
                node, 0, count, top.scope, top.subflows, top.invocations,
                top.repetitions, top.control_path,
            ),)
    return _Routed(replace(control, frames=()), None, None, operations)


def _view(control: _ActorControl, routed: _Routed | None = None) -> ActorControlState:
    terminal = not control.frames if routed is None else routed.step is None
    return ActorControlState(
        control.actor.address,
        None if routed is None else routed.step_address,
        terminal,
    )


def _generator_versions(document) -> Mapping[str, str]:
    from scenario_engine.manifest import GENERATOR_VERSIONS
    requirements = dict(GENERATOR_VERSIONS)
    for actor in document.actors:
        for sequence in (actor.steps, *actor.subflows.values()):
            for step in sequence:
                for declaration in step.generate.values():
                    if "$plugin" in declaration:
                        body = declaration["$plugin"]
                        prior = requirements.get(f"plugin:{body['name']}")
                        if prior is not None and prior != body["version"]:
                            raise ActorExecutionError("conflicting plugin version declarations")
                        requirements[f"plugin:{body['name']}"] = body["version"]
    return MappingProxyType({key: requirements[key] for key in sorted(requirements)})


def _schedule(scenario, root_seed, schedule_seed, run_index, resources, controls, decisions,
              classification, failure=None):
    from scenario_engine.schedule import (
        ScheduleArtifact, ScheduleExecution, ScheduleFailure, ScheduleRecord,
    )
    records = tuple(ScheduleRecord(
        item.ordinal, item.ready_actors, item.selected_actor,
        item.committed_history_length, item.logical_clock, item.scheduler_digest, item.outcome,
    ) for item in decisions)
    failed = None
    if failure is not None:
        code = getattr(failure, "code", type(failure).__name__)
        failed = ScheduleFailure(decisions[-1].selected_actor, str(code), decisions[-1].ordinal)
    return ScheduleArtifact(
        canonical_scenario_hash(scenario), resources.hashes(), run_index, schedule_seed,
        tuple(sorted(controls, key=str.encode)),
        ScheduleExecution(root_seed, scenario.reference_clock_start, _generator_versions(scenario.document)),
        records, classification, failed,
    )


def _outcome(runner, controls, decisions, classification, routed=None, schedule=None) -> ActorExecutionOutcome:
    routes = routed or {}
    return ActorExecutionOutcome(
        runner.state.snapshot(), runner.clock.current, runner.history.records,
        tuple(_view(control, routes.get(address)) for address, control in sorted(controls.items())),
        tuple(decisions), tuple(runner.artifacts), classification, schedule,
    )


def execute_actors_internal(
    scenario: CompiledScenarioV2,
    root_seed: str | int,
    schedule_seed: int,
    *,
    run_index: int = 0,
    inputs: Mapping[str, Any] | None = None,
    plugins: PluginRegistry | None = None,
    _expected_schedule: Any = None,
) -> ActorExecutionOutcome:
    """Execute validated DSL 2 actors without exposing a public Engine 2 result."""
    if not isinstance(scenario, CompiledScenarioV2):
        raise TypeError("scenario must be CompiledScenarioV2")
    if isinstance(run_index, bool) or not isinstance(run_index, int) or run_index < 0:
        raise ValueError("run_index must be a nonnegative integer")
    registry = EMPTY_PLUGIN_REGISTRY if plugins is None else plugins
    if not isinstance(registry, PluginRegistry):
        raise TypeError("plugins must be a PluginRegistry or None")
    resources = scenario.resources if scenario.resources is not None else resolve_resources(scenario.document.resources, inputs)
    if scenario.resources is not None and inputs is not None:
        raise ValueError("inputs must be supplied before compilation or to an unresolved scenario")
    validate_resources(resources, scenario.document.validators)
    for item in scenario.document.constraints:
        result = compile_constraint(item["check"], resources).evaluate(EvaluationEnvironment({}, {}, {}))
        if type(result) is not bool:
            raise ConstraintDefinitionError(f"constraint {item['id']}: check must return boolean")
        if not result:
            raise ConstraintViolation(f"constraint {item['id']} violated")

    runner = ScenarioRunner(
        root_seed, ExecutionAddress(scenario.scenario_id, run_index),
        ScenarioState(scenario.initial_state), LogicalClock(scenario.reference_clock_start),
    )
    controls = {
        actor.address: _ActorControl(actor, (_SequenceFrame(actor.steps, 0, None, actor.subflows),))
        for actor in scenario.actors
    }
    declared = tuple(controls)
    invariants = tuple(
        (item["id"], compile_expression(item["check"], resources))
        for item in scenario.document.invariants
    )
    decisions: list[ActorSchedulingDecision] = []
    scenario_hash = canonical_scenario_hash(scenario)
    resource_hashes = resources.hashes()

    if _expected_schedule is not None:
        from scenario_engine.schedule import (
            ENGINE2_EXECUTION_VERSION, ScheduleReplayMismatch, canonical_schedule_bytes,
        )
        expected_execution = _expected_schedule.execution
        checks = (
            ("scenario_hash", _expected_schedule.scenario_hash, scenario_hash),
            ("input_resource_hashes", dict(_expected_schedule.input_resource_hashes), dict(resource_hashes)),
            ("run_index", _expected_schedule.run_index, run_index),
            ("schedule_seed", _expected_schedule.schedule_seed, schedule_seed),
            ("actors", _expected_schedule.actors, tuple(sorted(declared, key=str.encode))),
            ("execution.root_seed", expected_execution.root_seed, root_seed),
            ("execution.reference_clock_start", expected_execution.reference_clock_start, scenario.reference_clock_start),
            ("execution.generator_versions", dict(expected_execution.generator_versions), dict(_generator_versions(scenario.document))),
            ("execution.engine_version", expected_execution.engine_version, ENGINE2_EXECUTION_VERSION),
        )
        for field, expected, received in checks:
            if expected != received:
                raise ScheduleReplayMismatch(field, "does not match replay coordinates")

    while True:
        state = runner.state.snapshot()
        routed = {
            address: _route(control, state, resources, registry, runner.state)
            for address, control in controls.items()
        }
        ready = tuple(address for address in declared if routed[address].step is not None)
        if not ready:
            if all(routed[address].step is None for address in controls):
                terminal_controls = {
                    address: replace(control, frames=()) for address, control in controls.items()
                }
                schedule = _schedule(scenario, root_seed, schedule_seed, run_index, resources,
                                     terminal_controls, decisions, "SUCCESS")
                if _expected_schedule is not None and canonical_schedule_bytes(schedule) != canonical_schedule_bytes(_expected_schedule):
                    raise ScheduleReplayMismatch("records", "record count or terminal outcome differs")
                return _outcome(runner, terminal_controls, decisions, "SUCCESS", routed, schedule)
            raise ActorExecutionError("no actor is ready while a nonterminal actor remains", code="ACTOR_SCHEDULER_STALLED")
        if len(decisions) >= MAX_SCHEDULER_SELECTIONS:
            raise ActorExecutionError(
                "scheduler selection limit exceeded before creating the next selection",
                code="ACTOR_SCHEDULER_SELECTION_LIMIT_EXCEEDED", limit="MAX_SCHEDULER_SELECTIONS",
            )
        coordinates = SchedulerInput(
            scenario_hash, resource_hashes, run_index, schedule_seed, len(decisions),
            len(runner.history.records), runner.clock.current, declared, ready,
        )
        selected: SchedulerDecision = select_actor(coordinates)
        route = routed[selected.selected_actor]
        assert route.step is not None and route.step_address is not None
        decision = ActorSchedulingDecision(
            len(decisions), selected.selected_actor, route.step_address,
            selected.ready_actors, selected.digest, len(runner.history.records), runner.clock.current,
        )
        if _expected_schedule is not None:
            ordinal = len(decisions)
            if ordinal >= len(_expected_schedule.records):
                raise ScheduleReplayMismatch("records", "contains a missing record")
            expected = _expected_schedule.records[ordinal]
            actual = (ordinal, selected.ready_actors, selected.selected_actor,
                      len(runner.history.records), runner.clock.current, selected.digest)
            recorded = (expected.selection_ordinal, expected.ready_actors, expected.selected_actor,
                        expected.committed_history_length, expected.logical_clock, expected.scheduler_digest)
            if recorded != actual:
                raise ScheduleReplayMismatch(f"records[{ordinal}]", "scheduler coordinates or decision differ")
        decisions.append(decision)
        actor = controls[selected.selected_actor].actor
        runner.address = ExecutionAddress(
            scenario.scenario_id, run_index, route.invocations, route.repetitions,
            actor_id=actor.actor_id,
        )

        spec, _faults = apply_step_faults(
            route.step.spec, scenario.document.faults, runner.address,
            runner.state.snapshot(), resources, route.scope, route.control_path,
        )

        def validator(candidate, address):
            evaluate_invariants(invariants, candidate.post_state, route.step.step_id, address,
                lambda invariant_id, outcome, execution_address, step_id: None)

        try:
            runner.run_step(spec, validator if invariants else None)
        except Exception as error:
            # ScenarioRunner commits only after candidate construction and validation.
            decisions[-1] = replace(decisions[-1], outcome="FAILED")
            schedule = _schedule(scenario, root_seed, schedule_seed, run_index, resources,
                                 controls, decisions, "FAILED", error)
            setattr(error, "actor_address", selected.selected_actor)
            setattr(error, "internal_outcome", _outcome(
                runner, controls, decisions, "FAILED", routed, schedule,
            ))
            if _expected_schedule is not None and canonical_schedule_bytes(schedule) != canonical_schedule_bytes(_expected_schedule):
                raise ScheduleReplayMismatch("terminal", "failure classification differs") from error
            raise
        controls[selected.selected_actor] = route.control
