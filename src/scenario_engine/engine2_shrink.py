"""Bounded, source-anchored whole-actor deletion for failed Engine 2 scenarios.

This module is intentionally not exported from :mod:`scenario_engine`.  It
does not define native evidence and it is not a general-purpose shrinker.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import math
from types import MappingProxyType
from typing import Any, Mapping
import unicodedata
from time import monotonic

import yaml

from .canonical import canonical_scenario_hash, canonical_scenario_payload
from .dsl.models import CompiledScenarioV2
from .dsl.parser import _DSLLoader
from .engine2 import (
    Engine2Result, canonical_result2_bytes, construct_result2,
    exact_replay_result2_internal, read_result2, validate_engine2,
)
from .invariants import InvariantViolation
from .resources import resolve_resources
from .schedule import (
    ScheduleArtifact, canonical_schedule_bytes, read_schedule,
)
from .scheduler import MAX_SCHEDULE_SEED
from .values import canonical_bytes, normalize


MAX_CANDIDATE_EVALUATIONS = 64
MAX_REPETITIONS = 16
MAX_TOTAL_EXECUTIONS = 1024
MAX_SOURCE_BYTES = 1_048_576
MAX_INPUT_BYTES = 262_144
FAILURE_PRESERVATION_LEVEL = "SOURCE_ANCHORED_SINGLE_INVARIANT_SIGNATURE"
ONE_MINIMAL = "1_MINIMAL_UNDER_ELIGIBLE_ACTOR_DELETION"
NOT_MINIMAL = "MINIMALITY_NOT_ESTABLISHED"


class Engine2ShrinkError(ValueError):
    """Stable request or transformation rejection without supplied values."""

    code = "ENGINE2_SHRINK_INVALID"

    def __init__(self, field_name: str, message: str) -> None:
        self.field_name = field_name
        super().__init__(f"{field_name}: {message}")


def _integer(value: object, field_name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise Engine2ShrinkError(field_name, "must be an integer excluding bool")
    if not minimum <= value <= maximum:
        raise Engine2ShrinkError(field_name, f"must be in inclusive range {minimum}..{maximum}")
    return value


def _freeze_inner(value: Any) -> Any:
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise Engine2ShrinkError("inputs", "must use string mapping keys")
        return MappingProxyType({key: _freeze_inner(value[key]) for key in sorted(value)})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_inner(item) for item in value)
    return value


def _freeze_inputs(value: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise Engine2ShrinkError("inputs", "must be a string-keyed mapping or None")
    try:
        normalize(value)
        frozen = _freeze_inner(value)
        encoded = canonical_bytes(frozen)
    except Engine2ShrinkError:
        raise
    except (TypeError, ValueError, RecursionError):
        raise Engine2ShrinkError("inputs", "contains an unsupported semantic value") from None
    if len(encoded) > MAX_INPUT_BYTES:
        raise Engine2ShrinkError("inputs", "exceeds bounded canonical input size")
    return frozen


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class Engine2ShrinkRequest:
    """All fixed coordinates and bounds for one local actor-deletion attempt."""

    source: str = field(repr=False)
    result: Engine2Result | bytes | str = field(repr=False)
    schedule: ScheduleArtifact | bytes | str = field(repr=False)
    root_seed: str | int
    schedule_seed: int
    run_index: int
    inputs: Mapping[str, Any] | None = field(repr=False)
    max_candidate_evaluations: int
    total_execution_budget: int
    deadline: float
    repetition_count: int = 3

    def __post_init__(self) -> None:
        if not isinstance(self.source, str):
            raise Engine2ShrinkError("source", "must be DSL 2 text")
        if len(self.source.encode("utf-8")) > MAX_SOURCE_BYTES:
            raise Engine2ShrinkError("source", "exceeds bounded UTF-8 source size")
        if not isinstance(self.result, (Engine2Result, bytes, str)):
            raise Engine2ShrinkError("result", "must be authoritative Result/2 evidence")
        if not isinstance(self.schedule, (ScheduleArtifact, bytes, str)):
            raise Engine2ShrinkError("schedule", "must be authoritative Schedule/1 evidence")
        if isinstance(self.root_seed, bool) or not isinstance(self.root_seed, (str, int)):
            raise Engine2ShrinkError("root_seed", "must be string or integer excluding bool")
        _integer(self.schedule_seed, "schedule_seed", 0, MAX_SCHEDULE_SEED)
        _integer(self.run_index, "run_index", 0, 2**63 - 1)
        _integer(self.max_candidate_evaluations, "max_candidate_evaluations", 1,
                 MAX_CANDIDATE_EVALUATIONS)
        _integer(self.repetition_count, "repetition_count", 3, MAX_REPETITIONS)
        _integer(self.total_execution_budget, "total_execution_budget", 1,
                 MAX_TOTAL_EXECUTIONS)
        if (isinstance(self.deadline, bool) or not isinstance(self.deadline, (int, float))
                or not math.isfinite(self.deadline) or self.deadline < 0):
            raise Engine2ShrinkError("deadline", "must be a finite nonnegative monotonic deadline")
        object.__setattr__(self, "deadline", float(self.deadline))
        object.__setattr__(self, "inputs", _freeze_inputs(self.inputs))


@dataclass(frozen=True, slots=True)
class Engine2ShrinkOutcome:
    """Noncanonical immutable summary; native children remain the evidence."""

    status: str
    reason: str
    original_source: str = field(repr=False)
    reduced_source: str = field(repr=False)
    original_counts: Mapping[str, int]
    reduced_counts: Mapping[str, int]
    removed_actor_addresses: tuple[str, ...]
    eligible_actor_addresses: tuple[str, ...]
    coordinates: Mapping[str, Any]
    failure_identity: Mapping[str, Any]
    baseline_scenario_hash: str | None
    final_scenario_hash: str | None
    baseline_result_hash: str | None
    final_result_hash: str | None
    baseline_schedule_hash: str | None
    final_schedule_hash: str | None
    final_result: Engine2Result | None = field(repr=False)
    final_schedule: ScheduleArtifact | None = field(repr=False)
    candidate_evaluations: int = 0
    execution_count: int = 0
    accepted_count: int = 0
    rejected_count: int = 0
    invalid_count: int = 0
    determinism_verified: bool = False
    replay_verified: bool = False
    complete_final_pass: bool = False
    minimality: str = NOT_MINIMAL
    preservation_level: str = FAILURE_PRESERVATION_LEVEL
    limitations: tuple[str, ...] = (
        "whole-actor deletion only",
        "source-anchored single-invariant identity, not a general semantic oracle",
        "no global minimality claim",
        "deadline checks occur between executions and are not hard execution timeouts",
        "trusted plugins are unsandboxed and excluded",
    )


@dataclass(slots=True)
class _Budget:
    request: Engine2ShrinkRequest
    executions: int = 0
    stop: str | None = None

    def take(self) -> bool:
        if monotonic() >= self.request.deadline:
            self.stop = "DEADLINE_REACHED"
            return False
        if self.executions >= self.request.total_execution_budget:
            self.stop = "TOTAL_EXECUTION_BUDGET_EXHAUSTED"
            return False
        self.executions += 1
        return True


@dataclass(frozen=True, slots=True)
class _Run:
    result: Engine2Result
    schedule: ScheduleArtifact
    invariant_id: str
    step_id: str


def _native_result(value: Engine2Result | bytes | str) -> Engine2Result:
    if isinstance(value, Engine2Result):
        return read_result2(canonical_result2_bytes(value))
    return read_result2(value)


def _native_schedule(value: ScheduleArtifact | bytes | str) -> ScheduleArtifact:
    if isinstance(value, ScheduleArtifact):
        return read_schedule(canonical_schedule_bytes(value))
    return read_schedule(value)


def _contains_plugin(scenario: CompiledScenarioV2) -> bool:
    for actor in scenario.document.actors:
        for sequence in (actor.steps, *actor.subflows.values()):
            for step in sequence:
                if any(isinstance(item, Mapping) and "$plugin" in item
                       for item in step.generate.values()):
                    return True
    return False


def _counts(scenario: CompiledScenarioV2 | None) -> Mapping[str, int]:
    if scenario is None:
        return MappingProxyType({"actors": 0, "declared_steps": 0})
    steps = sum(len(actor.steps) + sum(len(flow) for flow in actor.subflows.values())
                for actor in scenario.document.actors)
    return MappingProxyType({"actors": len(scenario.document.actors), "declared_steps": steps})


def _coordinates(request: Engine2ShrinkRequest) -> Mapping[str, Any]:
    inputs = MappingProxyType({}) if request.inputs is None else request.inputs
    return MappingProxyType({
        "input_hash": hashlib.sha256(canonical_bytes(inputs)).hexdigest(),
        "root_seed": request.root_seed,
        "run_index": request.run_index,
        "schedule_seed": request.schedule_seed,
    })


def _reject(request: Engine2ShrinkRequest, reason: str, *, scenario=None, result=None,
            schedule=None, budget=None, replay=False, deterministic=False) -> Engine2ShrinkOutcome:
    scenario_hash = None if scenario is None else canonical_scenario_hash(scenario)
    return Engine2ShrinkOutcome(
        "REJECTED", reason, request.source, request.source, _counts(scenario), _counts(scenario),
        (), (), _coordinates(request), MappingProxyType({}), scenario_hash, scenario_hash,
        None if result is None else result.result_hash,
        None if result is None else result.result_hash,
        None if schedule is None else schedule.schedule_hash,
        None if schedule is None else schedule.schedule_hash,
        result, schedule, execution_count=0 if budget is None else budget.executions,
        determinism_verified=deterministic, replay_verified=replay,
    )


def _run_failed(scenario: CompiledScenarioV2, request: Engine2ShrinkRequest,
                budget: _Budget) -> _Run | None:
    if not budget.take():
        return None
    from .engine2 import execute_engine2
    try:
        execute_engine2(
            scenario, request.root_seed, request.schedule_seed, run_index=request.run_index,
            inputs=None if request.inputs is None else _thaw(request.inputs), plugins=None,
        )
    except InvariantViolation as error:
        outcome = getattr(error, "internal_outcome", None)
        if outcome is None:
            return None
        return _Run(
            construct_result2(scenario, outcome), outcome.schedule,
            error.invariant_id, error.step_id,
        )
    except Exception:
        return None
    return None


def _replay(run: _Run, scenario: CompiledScenarioV2, request: Engine2ShrinkRequest,
            budget: _Budget) -> bool:
    if not budget.take():
        return False
    try:
        exact_replay_result2_internal(
            run.result, run.schedule, scenario,
            inputs=None if request.inputs is None else _thaw(request.inputs), plugins=None,
        )
    except Exception:
        return False
    return True


def _signature(result: Engine2Result) -> tuple[str, str | None, str | None, int | None]:
    failure = result.failure
    return (
        result.classification,
        None if failure is None else failure.code,
        None if failure is None else failure.actor,
        None if failure is None else failure.selection_ordinal,
    )


def _failure_signature(value: Any) -> tuple[str, str, int] | None:
    if value is None:
        return None
    return (value.actor, value.code, value.selection_ordinal)


def _payload_without_actors(scenario: CompiledScenarioV2) -> Mapping[str, Any]:
    payload = dict(canonical_scenario_payload(scenario))
    payload.pop("actors", None)
    return payload


def _actor_map(scenario: CompiledScenarioV2) -> dict[str, Any]:
    return {actor.address: actor for actor in scenario.document.actors}


def _safe_actor_layout(source: str, scenario: CompiledScenarioV2) -> tuple[str, ...]:
    """Validate the conservative block-sequence representation used for splicing."""
    try:
        root = yaml.compose(source, Loader=_DSLLoader)
    except yaml.YAMLError:
        raise Engine2ShrinkError("source", "cannot establish safe YAML node boundaries") from None
    if not isinstance(root, yaml.MappingNode):
        raise Engine2ShrinkError("source", "must have a block mapping root")
    actors = None
    for key, value in root.value:
        if isinstance(key, yaml.ScalarNode) and key.value == "actors":
            actors = value
            break
    if not isinstance(actors, yaml.SequenceNode) or actors.flow_style is not False:
        raise Engine2ShrinkError("source", "actors must use a block sequence")
    lines = source.splitlines(keepends=True)
    declared_ids: list[str] = []
    for node in actors.value:
        if not isinstance(node, yaml.MappingNode) or node.flow_style is not False:
            raise Engine2ShrinkError("source", "each actor must use a block mapping")
        line = lines[node.start_mark.line]
        prefix = line[:node.start_mark.column]
        if not prefix.endswith("- ") or prefix[:-2].strip():
            raise Engine2ShrinkError("source", "actor declarations must begin on separate block lines")
        actor_id = None
        for key, value in node.value:
            if isinstance(key, yaml.ScalarNode) and key.value == "id" and isinstance(value, yaml.ScalarNode):
                actor_id = unicodedata.normalize("NFC", value.value)
        if actor_id is None:
            raise Engine2ShrinkError("source", "actor ID boundary is ambiguous")
        declared_ids.append(actor_id)
    by_id = {actor.actor_id: actor.address for actor in scenario.document.actors}
    if len(by_id) != len(declared_ids) or set(by_id) != set(declared_ids):
        raise Engine2ShrinkError("source", "declared IDs do not map uniquely to compiled actors")
    return tuple(by_id[item] for item in declared_ids)


def _delete_actor(source: str, address: str) -> str:
    scenario = validate_engine2(source)
    declared = _safe_actor_layout(source, scenario)
    index = declared.index(address)
    root = yaml.compose(source, Loader=_DSLLoader)
    assert isinstance(root, yaml.MappingNode)
    actors = next(value for key, value in root.value if key.value == "actors")
    assert isinstance(actors, yaml.SequenceNode)
    node = actors.value[index]
    lines = source.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    start = offsets[node.start_mark.line]
    end_line = (actors.value[index + 1].start_mark.line if index + 1 < len(actors.value)
                else actors.end_mark.line)
    end = offsets[end_line]
    if not start < end:
        raise Engine2ShrinkError("source", "actor source boundary is empty or reversed")
    return source[:start] + source[end:]


def _content_guard(original: CompiledScenarioV2, candidate: CompiledScenarioV2,
                   removed: set[str], target: str) -> bool:
    if _payload_without_actors(original) != _payload_without_actors(candidate):
        return False
    before, after = _actor_map(original), _actor_map(candidate)
    if set(after) != set(before) - removed:
        return False
    if any(after[address] != before[address] for address in after):
        return False
    if target not in after or after[target] != before[target]:
        return False
    return len(candidate.document.invariants) == 1 and candidate.document.invariants == original.document.invariants


def shrink_failed_scenario(request: Engine2ShrinkRequest) -> Engine2ShrinkOutcome:
    """Greedily delete only originally unselected actors under strict native checks."""
    if not isinstance(request, Engine2ShrinkRequest):
        raise TypeError("request must be Engine2ShrinkRequest")
    budget = _Budget(request)
    try:
        baseline = validate_engine2(request.source)
        declared_order = _safe_actor_layout(request.source, baseline)
        accepted_result = _native_result(request.result)
        accepted_schedule = _native_schedule(request.schedule)
    except Exception:
        return _reject(request, "BASELINE_MALFORMED_OR_INVALID")

    if _contains_plugin(baseline):
        return _reject(request, "PLUGINS_UNSUPPORTED", scenario=baseline,
                       result=accepted_result, schedule=accepted_schedule, budget=budget)
    if len(baseline.document.invariants) != 1:
        return _reject(request, "EXACTLY_ONE_POST_STATE_INVARIANT_REQUIRED", scenario=baseline,
                       result=accepted_result, schedule=accepted_schedule, budget=budget)
    target_invariant = baseline.document.invariants[0]
    expected_signature = _signature(accepted_result)
    failure = accepted_result.failure
    if expected_signature[:2] != ("FAILED", "InvariantViolation") or failure is None:
        return _reject(request, "NATIVE_FAILED_INVARIANT_VIOLATION_REQUIRED", scenario=baseline,
                       result=accepted_result, schedule=accepted_schedule, budget=budget)
    target_actor = failure.actor
    actors = _actor_map(baseline)
    if target_actor not in actors:
        return _reject(request, "FAILING_ACTOR_NOT_DECLARED", scenario=baseline,
                       result=accepted_result, schedule=accepted_schedule, budget=budget)
    target_definition = actors[target_actor]
    if len(target_definition.steps) != 1 or target_definition.subflows:
        return _reject(request, "FAILING_ACTOR_MUST_HAVE_ONE_DIRECT_STEP", scenario=baseline,
                       result=accepted_result, schedule=accepted_schedule, budget=budget)
    target_step = target_definition.steps[0].step_id
    source_hash = canonical_scenario_hash(baseline)
    coordinate_checks = (
        accepted_result.manifest.scenario_hash == source_hash,
        accepted_schedule.scenario_hash == source_hash,
        accepted_result.manifest.root_seed == request.root_seed,
        accepted_schedule.execution.root_seed == request.root_seed,
        accepted_result.manifest.schedule_seed == request.schedule_seed,
        accepted_schedule.schedule_seed == request.schedule_seed,
        accepted_result.manifest.run_index == request.run_index,
        accepted_schedule.run_index == request.run_index,
        accepted_result.schedule_reference.schedule_hash == accepted_schedule.schedule_hash,
        _failure_signature(accepted_result.failure) == _failure_signature(accepted_schedule.failure),
        tuple(accepted_schedule.actors) == tuple(sorted(actors, key=str.encode)),
    )
    if not all(coordinate_checks):
        return _reject(request, "EVIDENCE_COORDINATES_OR_LINKAGE_MISMATCH", scenario=baseline,
                       result=accepted_result, schedule=accepted_schedule, budget=budget)
    try:
        resources = resolve_resources(
            baseline.document.resources,
            None if request.inputs is None else _thaw(request.inputs),
        )
    except Exception:
        return _reject(request, "INPUTS_OR_RESOURCES_INVALID", scenario=baseline,
                       result=accepted_result, schedule=accepted_schedule, budget=budget)
    if (dict(resources.hashes()) != dict(accepted_result.manifest.input_resource_hashes)
            or dict(resources.hashes()) != dict(accepted_schedule.input_resource_hashes)):
        return _reject(request, "RESOURCE_COORDINATES_MISMATCH", scenario=baseline,
                       result=accepted_result, schedule=accepted_schedule, budget=budget)

    accepted_result_bytes = canonical_result2_bytes(accepted_result)
    accepted_schedule_bytes = canonical_schedule_bytes(accepted_schedule)
    accepted_run = _Run(accepted_result, accepted_schedule, target_invariant["id"], target_step)
    if not _replay(accepted_run, baseline, request, budget):
        reason = budget.stop or "BASELINE_EXACT_REPLAY_FAILED"
        return _reject(request, reason, scenario=baseline, result=accepted_result,
                       schedule=accepted_schedule, budget=budget)
    for _ in range(request.repetition_count):
        reproduced = _run_failed(baseline, request, budget)
        if reproduced is None:
            reason = budget.stop or "BASELINE_NATIVE_REPRODUCTION_FAILED"
            return _reject(request, reason, scenario=baseline, result=accepted_result,
                           schedule=accepted_schedule, budget=budget, replay=True)
        if (canonical_result2_bytes(reproduced.result) != accepted_result_bytes
                or canonical_schedule_bytes(reproduced.schedule) != accepted_schedule_bytes
                or reproduced.invariant_id != target_invariant["id"]
                or reproduced.step_id != target_step):
            return _reject(request, "BASELINE_NOT_DETERMINISTIC_OR_TARGET_MISMATCH",
                           scenario=baseline, result=accepted_result,
                           schedule=accepted_schedule, budget=budget, replay=True)

    selected = {record.selected_actor for record in accepted_schedule.records}
    eligible = tuple(sorted(
        (address for address in declared_order if address != target_actor and address not in selected),
        key=str.encode,
    ))
    current_source, current_scenario = request.source, baseline
    current_result, current_schedule = accepted_result, accepted_schedule
    removed: list[str] = []
    evaluations = accepted = rejected = invalid = 0
    complete_pass = False
    stop_reason = "NO_FURTHER_ACCEPTABLE_DELETION"

    while True:
        pass_completed = True
        changed = False
        for address in eligible:
            if address in removed:
                continue
            if evaluations >= request.max_candidate_evaluations:
                stop_reason = "EVALUATION_BUDGET_EXHAUSTED"
                pass_completed = False
                break
            if monotonic() >= request.deadline:
                stop_reason = "DEADLINE_REACHED"
                pass_completed = False
                break
            evaluations += 1
            try:
                candidate_source = _delete_actor(current_source, address)
                candidate = validate_engine2(candidate_source)
                _safe_actor_layout(candidate_source, candidate)
            except Exception:
                invalid += 1
                continue
            candidate_removed = set(removed) | {address}
            if (len(candidate.document.actors) >= len(current_scenario.document.actors)
                    or not _content_guard(baseline, candidate, candidate_removed, target_actor)):
                invalid += 1
                continue
            runs: list[_Run] = []
            for _ in range(request.repetition_count):
                run = _run_failed(candidate, request, budget)
                if run is None:
                    break
                runs.append(run)
            if budget.stop is not None:
                stop_reason = budget.stop
                pass_completed = False
                break
            if len(runs) != request.repetition_count:
                rejected += 1
                continue
            first = runs[0]
            result_bytes = canonical_result2_bytes(first.result)
            schedule_bytes = canonical_schedule_bytes(first.schedule)
            same_native = all(
                canonical_result2_bytes(item.result) == result_bytes
                and canonical_schedule_bytes(item.schedule) == schedule_bytes
                for item in runs
            )
            predicate = (
                same_native
                and _signature(first.result) == expected_signature
                and all(item.invariant_id == target_invariant["id"] for item in runs)
                and all(item.step_id == target_step for item in runs)
                and first.schedule.failure is not None
                and _failure_signature(first.result.failure) == _failure_signature(first.schedule.failure)
                and first.result.schedule_reference.schedule_hash == first.schedule.schedule_hash
                and first.result.manifest.scenario_hash == canonical_scenario_hash(candidate)
                and first.schedule.scenario_hash == canonical_scenario_hash(candidate)
                and dict(first.result.manifest.input_resource_hashes) == dict(accepted_result.manifest.input_resource_hashes)
            )
            if not predicate or not _replay(first, candidate, request, budget):
                if budget.stop is not None:
                    stop_reason = budget.stop
                    pass_completed = False
                    break
                rejected += 1
                continue
            current_source, current_scenario = candidate_source, candidate
            current_result, current_schedule = first.result, first.schedule
            removed.append(address)
            accepted += 1
            changed = True
            break
        if not pass_completed:
            break
        if changed:
            continue
        complete_pass = True
        break

    minimality = ONE_MINIMAL if complete_pass else NOT_MINIMAL
    status = "REDUCED" if removed else "NO_REDUCTION"
    identity = MappingProxyType({
        "actor": target_actor,
        "code": "InvariantViolation",
        "invariant_expression": _freeze_inner(target_invariant["check"]),
        "invariant_id": target_invariant["id"],
        "selection_ordinal": failure.selection_ordinal,
        "step_id": target_step,
    })
    return Engine2ShrinkOutcome(
        status, stop_reason, request.source, current_source, _counts(baseline),
        _counts(current_scenario), tuple(removed), eligible, _coordinates(request), identity,
        source_hash, canonical_scenario_hash(current_scenario), accepted_result.result_hash,
        current_result.result_hash, accepted_schedule.schedule_hash,
        current_schedule.schedule_hash, current_result, current_schedule,
        evaluations, budget.executions, accepted, rejected, invalid, True, True,
        complete_pass, minimality,
    )


__all__ = (
    "Engine2ShrinkError", "Engine2ShrinkOutcome", "Engine2ShrinkRequest",
    "FAILURE_PRESERVATION_LEVEL", "MAX_CANDIDATE_EVALUATIONS",
    "shrink_failed_scenario",
)
