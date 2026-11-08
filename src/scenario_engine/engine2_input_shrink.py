"""Bounded list-element deletion for explicit Engine 2 input trees.

This module is intentionally module-qualified and noncanonical.  It reuses
native Result/2 and Schedule/1 construction and replay; it defines no evidence
format and performs no general-purpose value shrinking.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
import math
from time import monotonic
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .canonical import canonical_scenario_hash
from .dsl.models import CompiledScenarioV2
from .engine2 import (
    Engine2Result, canonical_result2_bytes, construct_result2,
    exact_replay_result2_internal, read_result2, validate_engine2,
)
from .ids import LogicalID
from .invariants import InvariantViolation
from .resources import resolve_resources
from .schedule import ScheduleArtifact, canonical_schedule_bytes, read_schedule
from .scheduler import MAX_SCHEDULE_SEED
from .values import MISSING, canonical_bytes


MAX_CANDIDATE_EVALUATIONS = 64
MAX_TOTAL_EXECUTIONS = 128
MAX_REPETITIONS = 16
MAX_INPUT_BYTES = 262_144
MAX_INPUT_NESTING_DEPTH = 32
MAX_SOURCE_BYTES = 1_048_576
FAILURE_PRESERVATION_LEVEL = "SOURCE_ANCHORED_SINGLE_INVARIANT_SIGNATURE"
ONE_MINIMAL = "1_MINIMAL_UNDER_ELIGIBLE_LIST_DELETIONS"
NOT_MINIMAL = "MINIMALITY_NOT_ESTABLISHED"

Path = tuple[str | int, ...]
Removal = tuple[Path, int]


class Engine2InputShrinkError(ValueError):
    """Stable validation error that never reflects supplied input values."""

    code = "ENGINE2_INPUT_SHRINK_INVALID"

    def __init__(self, field_name: str, message: str) -> None:
        self.field_name = field_name
        super().__init__(f"{field_name}: {message}")


def _integer(value: object, field_name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise Engine2InputShrinkError(field_name, "must be an integer excluding bool")
    if not minimum <= value <= maximum:
        raise Engine2InputShrinkError(
            field_name, f"must be in inclusive range {minimum}..{maximum}",
        )
    return value


_SCALARS = (type(None), bool, int, str, Decimal, datetime, timedelta, LogicalID)


def _copy_validate(value: Any, *, seen: set[int], level: int = 0,
                   field_name: str = "inputs") -> Any:
    """Copy a strict semantic tree without invoking user copy protocols."""
    if level > MAX_INPUT_NESTING_DEPTH:
        raise Engine2InputShrinkError(field_name, "exceeds maximum nesting depth")
    if type(value) is dict:
        identity = id(value)
        if identity in seen:
            raise Engine2InputShrinkError(field_name, "contains a cycle or mutable alias")
        seen.add(identity)
        if not all(type(key) is str for key in value):
            raise Engine2InputShrinkError(field_name, "must use exact string mapping keys")
        copied = {key: _copy_validate(value[key], seen=seen, level=level + 1,
                                      field_name=field_name)
                  for key in sorted(value)}
        return copied
    if type(value) is list:
        identity = id(value)
        if identity in seen:
            raise Engine2InputShrinkError(field_name, "contains a cycle or mutable alias")
        seen.add(identity)
        copied = [_copy_validate(item, seen=seen, level=level + 1,
                                 field_name=field_name) for item in value]
        return copied
    if type(value) not in _SCALARS and value is not MISSING:
        raise Engine2InputShrinkError(field_name, "contains an unsupported or ambiguous value type")
    try:
        canonical_bytes(value)
    except (TypeError, ValueError, ArithmeticError, RecursionError):
        raise Engine2InputShrinkError(field_name, "contains an unsupported semantic value") from None
    return value


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(value[key]) for key in sorted(value)})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(value[key]) for key in value}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _input_snapshot(value: object) -> Mapping[str, Any]:
    # Support dataclasses.replace() on an already validated request without
    # weakening the external exact-dict/list input boundary.
    if type(value) is MappingProxyType:
        value = _thaw(value)
    if type(value) is not dict:
        raise Engine2InputShrinkError("inputs", "must be an exact dict input tree")
    copied = _copy_validate(value, seen=set())
    encoded = canonical_bytes(copied)
    if len(encoded) > MAX_INPUT_BYTES:
        raise Engine2InputShrinkError("inputs", "exceeds bounded canonical input size")
    return _freeze(copied)


def _summary_mapping(value: object, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise Engine2InputShrinkError(field_name, "must be a string-keyed mapping")
    thawed = _thaw(value)
    copied = _copy_validate(thawed, seen=set(), field_name=field_name)
    return _freeze(copied)


def _path_key(path: Path) -> tuple[bytes, ...]:
    return tuple((b"s:" + item.encode("utf-8")) if isinstance(item, str)
                 else (b"i:" + str(item).encode("ascii")) for item in path)


def _paths(value: object | None) -> tuple[Path, ...] | None:
    if value is None:
        return None
    if isinstance(value, (str, bytes, Mapping)) or not isinstance(value, Sequence):
        raise Engine2InputShrinkError("eligible_input_paths", "must be an ordered sequence of paths")
    checked: list[Path] = []
    for raw in value:
        if isinstance(raw, (str, bytes, Mapping)) or not isinstance(raw, Sequence) or not raw:
            raise Engine2InputShrinkError("eligible_input_paths", "must contain nonempty paths")
        path: list[str | int] = []
        for segment in raw:
            if type(segment) is str and segment:
                path.append(segment)
            elif type(segment) is int and segment >= 0:
                path.append(segment)
            else:
                raise Engine2InputShrinkError(
                    "eligible_input_paths", "path segments must be nonempty strings or nonnegative integers",
                )
        checked.append(tuple(path))
    if len(checked) != len(set(checked)):
        raise Engine2InputShrinkError("eligible_input_paths", "contains a duplicate path")
    return tuple(sorted(checked, key=_path_key))


def _removals(value: object) -> tuple[Removal, ...]:
    if isinstance(value, (str, bytes, Mapping)) or not isinstance(value, Sequence):
        raise Engine2InputShrinkError("removed", "must be an ordered sequence")
    checked: list[Removal] = []
    for raw in value:
        if isinstance(raw, (str, bytes, Mapping)) or not isinstance(raw, Sequence) or len(raw) != 2:
            raise Engine2InputShrinkError("removed", "must contain path/index pairs")
        paths = _paths((raw[0],))
        assert paths is not None
        checked.append((paths[0], _integer(raw[1], "removed", 0, 2**63 - 1)))
    return tuple(checked)


@dataclass(frozen=True, slots=True)
class Engine2InputShrinkRequest:
    """Fixed evidence, execution coordinates, input tree, and strict bounds."""

    source: str = field(repr=False)
    result: Engine2Result | bytes | str = field(repr=False)
    schedule: ScheduleArtifact | bytes | str = field(repr=False)
    root_seed: str | int
    schedule_seed: int
    run_index: int
    inputs: Mapping[str, Any] = field(repr=False)
    eligible_input_paths: tuple[Path, ...] | None = None
    max_candidate_evaluations: int = 64
    total_execution_budget: int = 128
    repetition_count: int = 3
    deadline: float = 0.0

    def __post_init__(self) -> None:
        if not isinstance(self.source, str):
            raise Engine2InputShrinkError("source", "must be DSL 2 text")
        if len(self.source.encode("utf-8")) > MAX_SOURCE_BYTES:
            raise Engine2InputShrinkError("source", "exceeds bounded UTF-8 source size")
        if not isinstance(self.result, (Engine2Result, bytes, str)):
            raise Engine2InputShrinkError("result", "must be authoritative Result/2 evidence")
        if not isinstance(self.schedule, (ScheduleArtifact, bytes, str)):
            raise Engine2InputShrinkError("schedule", "must be authoritative Schedule/1 evidence")
        if isinstance(self.root_seed, bool) or not isinstance(self.root_seed, (str, int)):
            raise Engine2InputShrinkError("root_seed", "must be string or integer excluding bool")
        _integer(self.schedule_seed, "schedule_seed", 0, MAX_SCHEDULE_SEED)
        _integer(self.run_index, "run_index", 0, 2**63 - 1)
        _integer(self.max_candidate_evaluations, "max_candidate_evaluations", 1,
                 MAX_CANDIDATE_EVALUATIONS)
        _integer(self.total_execution_budget, "total_execution_budget", 1,
                 MAX_TOTAL_EXECUTIONS)
        _integer(self.repetition_count, "repetition_count", 3, MAX_REPETITIONS)
        if (isinstance(self.deadline, bool) or not isinstance(self.deadline, (int, float))
                or not math.isfinite(self.deadline) or self.deadline < 0):
            raise Engine2InputShrinkError("deadline", "must be a finite nonnegative monotonic deadline")
        object.__setattr__(self, "deadline", float(self.deadline))
        object.__setattr__(self, "inputs", _input_snapshot(self.inputs))
        object.__setattr__(self, "eligible_input_paths", _paths(self.eligible_input_paths))


@dataclass(frozen=True, slots=True)
class Engine2InputShrinkOutcome:
    """Immutable noncanonical summary; native children remain authoritative."""

    status: str
    stop_reason: str
    original_input_size: int
    reduced_input_size: int
    original_inputs: Mapping[str, Any] = field(repr=False)
    reduced_inputs: Mapping[str, Any] = field(repr=False)
    removed: tuple[Removal, ...] = field(repr=False)
    eligible_input_paths: tuple[Path, ...] = field(repr=False)
    coordinates: Mapping[str, Any]
    failure_identity: Mapping[str, Any]
    original_result_hash: str | None
    final_result_hash: str | None
    original_schedule_hash: str | None
    final_schedule_hash: str | None
    final_result: Engine2Result | None = field(repr=False)
    final_schedule: ScheduleArtifact | None = field(repr=False)
    candidate_evaluations: int = 0
    execution_count: int = 0
    accepted_count: int = 0
    rejected_count: int = 0
    invalid_count: int = 0
    rejection_reasons: tuple[str, ...] = ()
    determinism_verified: bool = False
    replay_verified: bool = False
    complete_final_pass: bool = False
    minimality: str = NOT_MINIMAL
    preservation_level: str = FAILURE_PRESERVATION_LEVEL
    limitations: tuple[str, ...] = (
        "list-element deletion only; no key deletion, scalar rewrite, or reordering",
        "source-anchored single-invariant signature is not proof of full semantic equivalence",
        "conditional one-deletion minimality only; no global minimum claim",
        "deadline is cooperative between trusted executions, not a hard kill",
        "noncanonical summary is not tamper-proof native evidence",
    )

    def __post_init__(self) -> None:
        original = _input_snapshot(self.original_inputs)
        reduced = _input_snapshot(self.reduced_inputs)
        if self.original_input_size != len(canonical_bytes(original)):
            raise Engine2InputShrinkError("original_input_size", "does not match original_inputs")
        if self.reduced_input_size != len(canonical_bytes(reduced)):
            raise Engine2InputShrinkError("reduced_input_size", "does not match reduced_inputs")
        if self.reduced_input_size > self.original_input_size:
            raise Engine2InputShrinkError("reduced_input_size", "must not exceed original_input_size")
        paths = _paths(self.eligible_input_paths)
        if paths is None:
            raise Engine2InputShrinkError("eligible_input_paths", "must be supplied")
        object.__setattr__(self, "original_inputs", original)
        object.__setattr__(self, "reduced_inputs", reduced)
        object.__setattr__(self, "removed", _removals(self.removed))
        object.__setattr__(self, "eligible_input_paths", paths)
        object.__setattr__(self, "coordinates", _summary_mapping(self.coordinates, "coordinates"))
        object.__setattr__(self, "failure_identity", _summary_mapping(
            self.failure_identity, "failure_identity",
        ))
        object.__setattr__(self, "rejection_reasons", tuple(self.rejection_reasons))
        object.__setattr__(self, "limitations", tuple(self.limitations))


@dataclass(slots=True)
class _Budget:
    request: Engine2InputShrinkRequest
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
    return read_result2(canonical_result2_bytes(value)) if isinstance(value, Engine2Result) else read_result2(value)


def _native_schedule(value: ScheduleArtifact | bytes | str) -> ScheduleArtifact:
    return read_schedule(canonical_schedule_bytes(value)) if isinstance(value, ScheduleArtifact) else read_schedule(value)


def _contains_plugin(scenario: CompiledScenarioV2) -> bool:
    return any(
        isinstance(declaration, Mapping) and "$plugin" in declaration
        for actor in scenario.document.actors
        for sequence in (actor.steps, *actor.subflows.values())
        for step in sequence
        for declaration in step.generate.values()
    )


def _consumed_paths(node: Any) -> frozenset[tuple[str, ...]]:
    paths: set[tuple[str, ...]] = set()
    def visit(item: Any) -> None:
        if isinstance(item, Mapping):
            if "$input" in item and len(item) == 1 and isinstance(item["$input"], str):
                paths.add(tuple(item["$input"].split(".")))
            else:
                for key in sorted(item):
                    visit(item[key])
        elif isinstance(item, (list, tuple)):
            for child in item:
                visit(child)
    visit(node)
    return frozenset(paths)


def _get(root: Any, path: Path) -> Any:
    current = root
    for segment in path:
        if isinstance(segment, str):
            if not isinstance(current, Mapping) or segment not in current:
                raise KeyError
            current = current[segment]
        else:
            if not isinstance(current, (list, tuple)) or segment >= len(current):
                raise KeyError
            current = current[segment]
    return current


def _is_consumed_path(path: Path, consumed: frozenset[tuple[str, ...]]) -> bool:
    return any(path[:len(prefix)] == prefix for prefix in consumed)


def _discover_lists(root: Mapping[str, Any], consumed: frozenset[tuple[str, ...]]) -> tuple[Path, ...]:
    found: set[Path] = set()
    def visit(value: Any, path: Path) -> None:
        if isinstance(value, (list, tuple)):
            found.add(path)
            for index, item in enumerate(value):
                visit(item, path + (index,))
        elif isinstance(value, Mapping):
            for key in sorted(value):
                visit(value[key], path + (key,))
    for path in sorted(consumed, key=_path_key):
        try:
            visit(_get(root, path), path)
        except KeyError:
            continue
    return tuple(sorted(found, key=_path_key))


def _delete(inputs: Mapping[str, Any], path: Path, index: int) -> dict[str, Any]:
    candidate = _thaw(inputs)
    target = _get(candidate, path)
    if not isinstance(target, list) or index >= len(target):
        raise KeyError
    del target[index]
    return candidate


def _translate(path: Path, original_index: int | None,
               accepted: Sequence[Removal]) -> tuple[Path, int | None]:
    """Translate one frozen original coordinate after accepted deletions."""
    translated: list[str | int] = []
    original_prefix: Path = ()
    for segment in path:
        if isinstance(segment, str):
            translated.append(segment)
        else:
            deleted = tuple(index for removed_path, index in accepted
                            if removed_path == original_prefix)
            if segment in deleted:
                raise KeyError
            translated.append(segment - sum(index < segment for index in deleted))
        original_prefix += (segment,)
    if original_index is None:
        return tuple(translated), None
    deleted = tuple(index for removed_path, index in accepted if removed_path == path)
    if original_index in deleted:
        raise KeyError
    return tuple(translated), original_index - sum(index < original_index for index in deleted)


def _one_deletion(before: Mapping[str, Any], after: Mapping[str, Any], path: Path, index: int) -> bool:
    try:
        expected = _delete(before, path, index)
    except KeyError:
        return False
    return expected == _thaw(after)


def _run(scenario: CompiledScenarioV2, request: Engine2InputShrinkRequest,
         inputs: Mapping[str, Any], budget: _Budget) -> _Run | None:
    if not budget.take():
        return None
    from .engine2 import execute_engine2
    try:
        execute_engine2(
            scenario, request.root_seed, request.schedule_seed,
            run_index=request.run_index, inputs=_thaw(inputs), plugins=None,
        )
    except InvariantViolation as error:
        outcome = getattr(error, "internal_outcome", None)
        if outcome is None:
            return None
        return _Run(construct_result2(scenario, outcome), outcome.schedule,
                    error.invariant_id, error.step_id)
    except Exception:
        return None
    return None


def _replay(run: _Run, scenario: CompiledScenarioV2,
            inputs: Mapping[str, Any], budget: _Budget) -> bool:
    if not budget.take():
        return False
    try:
        exact_replay_result2_internal(
            run.result, run.schedule, scenario, inputs=_thaw(inputs), plugins=None,
        )
    except Exception:
        return False
    return True


def _signature(result: Engine2Result) -> tuple[str, str | None, str | None, int | None]:
    failure = result.failure
    return (result.classification, None if failure is None else failure.code,
            None if failure is None else failure.actor,
            None if failure is None else failure.selection_ordinal)


def _linked(result: Engine2Result, schedule: ScheduleArtifact) -> bool:
    failure = result.failure
    scheduled = schedule.failure
    return (
        result.schedule_reference.schedule_hash == schedule.schedule_hash
        and result.manifest.scenario_hash == schedule.scenario_hash
        and dict(result.manifest.input_resource_hashes) == dict(schedule.input_resource_hashes)
        and failure is not None and scheduled is not None
        and (failure.actor, failure.code, failure.selection_ordinal)
        == (scheduled.actor, scheduled.code, scheduled.selection_ordinal)
    )


def _coordinates(request: Engine2InputShrinkRequest) -> Mapping[str, Any]:
    return MappingProxyType({
        "root_seed": request.root_seed, "run_index": request.run_index,
        "schedule_seed": request.schedule_seed,
    })


def _outcome(request: Engine2InputShrinkRequest, reason: str, *, status: str = "REJECTED",
             inputs: Mapping[str, Any] | None = None, original_size: int | None = None,
             paths: tuple[Path, ...] = (), removed: tuple[Removal, ...] = (), result=None,
             schedule=None, original_result=None, original_schedule=None, budget=None,
             evaluations=0, accepted=0, rejected=0, invalid=0, reasons=(), deterministic=False,
             replay=False, complete=False) -> Engine2InputShrinkOutcome:
    original = request.inputs
    current = original if inputs is None else _freeze(_thaw(inputs))
    first_size = len(canonical_bytes(original)) if original_size is None else original_size
    return Engine2InputShrinkOutcome(
        status, reason, first_size, len(canonical_bytes(current)), original, current,
        removed, paths, _coordinates(request), MappingProxyType({}),
        None if original_result is None else original_result.result_hash,
        None if result is None else result.result_hash,
        None if original_schedule is None else original_schedule.schedule_hash,
        None if schedule is None else schedule.schedule_hash,
        result, schedule, evaluations, 0 if budget is None else budget.executions,
        accepted, rejected, invalid, tuple(reasons), deterministic, replay, complete,
        ONE_MINIMAL if complete else NOT_MINIMAL,
    )


def shrink_failed_inputs(request: Engine2InputShrinkRequest) -> Engine2InputShrinkOutcome:
    """Greedily delete one element at a time from frozen eligible input lists."""
    if not isinstance(request, Engine2InputShrinkRequest):
        raise TypeError("request must be Engine2InputShrinkRequest")
    budget = _Budget(request)
    original_size = len(canonical_bytes(request.inputs))
    try:
        scenario = validate_engine2(request.source)
        original_result = _native_result(request.result)
        original_schedule = _native_schedule(request.schedule)
    except Exception:
        return _outcome(request, "BASELINE_MALFORMED_OR_INVALID", budget=budget)
    if _contains_plugin(scenario):
        return _outcome(request, "PLUGINS_UNSUPPORTED", result=original_result,
                        schedule=original_schedule, original_result=original_result,
                        original_schedule=original_schedule, budget=budget)
    if len(scenario.document.invariants) != 1:
        return _outcome(request, "EXACTLY_ONE_POST_STATE_INVARIANT_REQUIRED", result=original_result,
                        schedule=original_schedule, original_result=original_result,
                        original_schedule=original_schedule, budget=budget)
    invariant = scenario.document.invariants[0]
    expected = _signature(original_result)
    failure = original_result.failure
    if expected[:2] != ("FAILED", "InvariantViolation") or failure is None:
        return _outcome(request, "NATIVE_FAILED_INVARIANT_VIOLATION_REQUIRED", result=original_result,
                        schedule=original_schedule, original_result=original_result,
                        original_schedule=original_schedule, budget=budget)
    actors = {actor.address: actor for actor in scenario.document.actors}
    if failure.actor not in actors:
        return _outcome(request, "FAILING_ACTOR_NOT_DECLARED", result=original_result,
                        schedule=original_schedule, original_result=original_result,
                        original_schedule=original_schedule, budget=budget)
    scenario_hash = canonical_scenario_hash(scenario)
    coordinates_ok = (
        original_result.manifest.scenario_hash == scenario_hash
        and original_schedule.scenario_hash == scenario_hash
        and original_result.manifest.root_seed == request.root_seed
        and original_schedule.execution.root_seed == request.root_seed
        and original_result.manifest.schedule_seed == request.schedule_seed
        and original_schedule.schedule_seed == request.schedule_seed
        and original_result.manifest.run_index == request.run_index
        and original_schedule.run_index == request.run_index
        and _linked(original_result, original_schedule)
        and tuple(original_schedule.actors) == tuple(sorted(actors, key=str.encode))
    )
    if not coordinates_ok:
        return _outcome(request, "EVIDENCE_COORDINATES_OR_LINKAGE_MISMATCH", result=original_result,
                        schedule=original_schedule, original_result=original_result,
                        original_schedule=original_schedule, budget=budget)
    try:
        resources = resolve_resources(scenario.document.resources, _thaw(request.inputs))
    except Exception:
        return _outcome(request, "INPUTS_OR_RESOURCES_INVALID", result=original_result,
                        schedule=original_schedule, original_result=original_result,
                        original_schedule=original_schedule, budget=budget)
    if (dict(resources.hashes()) != dict(original_result.manifest.input_resource_hashes)
            or dict(resources.hashes()) != dict(original_schedule.input_resource_hashes)):
        return _outcome(request, "RESOURCE_COORDINATES_MISMATCH", result=original_result,
                        schedule=original_schedule, original_result=original_result,
                        original_schedule=original_schedule, budget=budget)

    baseline = _Run(original_result, original_schedule, invariant["id"], "")
    if not _replay(baseline, scenario, request.inputs, budget):
        return _outcome(request, budget.stop or "BASELINE_EXACT_REPLAY_FAILED", result=original_result,
                        schedule=original_schedule, original_result=original_result,
                        original_schedule=original_schedule, budget=budget)
    result_bytes = canonical_result2_bytes(original_result)
    schedule_bytes = canonical_schedule_bytes(original_schedule)
    baseline_runs: list[_Run] = []
    for _ in range(request.repetition_count):
        run = _run(scenario, request, request.inputs, budget)
        if run is None:
            return _outcome(request, budget.stop or "BASELINE_NATIVE_REPRODUCTION_FAILED",
                            result=original_result, schedule=original_schedule,
                            original_result=original_result, original_schedule=original_schedule,
                            budget=budget, replay=True)
        baseline_runs.append(run)
    first_runtime = baseline_runs[0]
    declared_steps = {step.step_id for sequence in (
        actors[failure.actor].steps, *actors[failure.actor].subflows.values()) for step in sequence}
    if (first_runtime.invariant_id != invariant["id"] or first_runtime.step_id not in declared_steps
            or any(canonical_result2_bytes(run.result) != result_bytes
                   or canonical_schedule_bytes(run.schedule) != schedule_bytes
                   or run.invariant_id != first_runtime.invariant_id
                   or run.step_id != first_runtime.step_id for run in baseline_runs)):
        return _outcome(request, "BASELINE_NOT_DETERMINISTIC_OR_TARGET_MISMATCH",
                        result=original_result, schedule=original_schedule,
                        original_result=original_result, original_schedule=original_schedule,
                        budget=budget, replay=True)

    consumed = _consumed_paths(scenario.document.resources)
    discovered = _discover_lists(request.inputs, consumed)
    if request.eligible_input_paths is None:
        eligible = discovered
    else:
        eligible = request.eligible_input_paths
        try:
            valid_paths = all(_is_consumed_path(path, consumed)
                              and isinstance(_get(request.inputs, path), tuple)
                              for path in eligible)
        except KeyError:
            valid_paths = False
        if not valid_paths:
            return _outcome(request, "ELIGIBLE_INPUT_PATH_INVALID_OR_UNCONSUMED",
                            paths=eligible, result=original_result, schedule=original_schedule,
                            original_result=original_result, original_schedule=original_schedule,
                            budget=budget, deterministic=True, replay=True)

    current = request.inputs
    current_result, current_schedule = original_result, original_schedule
    removals: list[Removal] = []
    evaluations = accepted = rejected = invalid = 0
    rejection_reasons: list[str] = []
    original_lengths = {path: len(_get(request.inputs, path)) for path in eligible}
    complete = False
    stop_reason = "NO_FURTHER_ACCEPTABLE_DELETION"
    while True:
        changed = False
        pass_completed = True
        for path in eligible:
            try:
                current_path, _ = _translate(path, None, removals)
                target = _get(current, current_path)
            except KeyError:
                invalid += 1
                rejection_reasons.append("ELIGIBLE_PATH_BECAME_INVALID")
                continue
            if not isinstance(target, tuple):
                invalid += 1
                rejection_reasons.append("ELIGIBLE_PATH_BECAME_INVALID")
                continue
            for original_index in range(original_lengths[path]):
                try:
                    current_path, translated_index = _translate(path, original_index, removals)
                except KeyError:
                    continue
                assert translated_index is not None
                if translated_index >= len(target):
                    invalid += 1
                    rejection_reasons.append("ELIGIBLE_PATH_BECAME_INVALID")
                    continue
                if evaluations >= request.max_candidate_evaluations:
                    stop_reason, pass_completed = "EVALUATION_BUDGET_EXHAUSTED", False
                    break
                if monotonic() >= request.deadline:
                    stop_reason, pass_completed = "DEADLINE_REACHED", False
                    break
                evaluations += 1
                try:
                    raw_candidate = _delete(current, current_path, translated_index)
                    candidate = _input_snapshot(raw_candidate)
                except Exception:
                    invalid += 1
                    rejection_reasons.append("CANDIDATE_TRANSFORMATION_INVALID")
                    continue
                if (not _one_deletion(current, candidate, current_path, translated_index)
                        or len(canonical_bytes(candidate)) >= len(canonical_bytes(current))):
                    invalid += 1
                    rejection_reasons.append("NOT_STRICT_ALLOWED_DELETION")
                    continue
                try:
                    candidate_resources = resolve_resources(scenario.document.resources, _thaw(candidate))
                except Exception:
                    invalid += 1
                    rejection_reasons.append("RESOURCE_RESOLUTION_FAILED")
                    continue
                runs: list[_Run] = []
                for _ in range(request.repetition_count):
                    run = _run(scenario, request, candidate, budget)
                    if run is None:
                        break
                    runs.append(run)
                if budget.stop is not None:
                    stop_reason, pass_completed = budget.stop, False
                    break
                if len(runs) != request.repetition_count:
                    rejected += 1
                    rejection_reasons.append("CANDIDATE_NOT_NATIVE_FAILED")
                    continue
                first = runs[0]
                candidate_result_bytes = canonical_result2_bytes(first.result)
                candidate_schedule_bytes = canonical_schedule_bytes(first.schedule)
                same = all(canonical_result2_bytes(run.result) == candidate_result_bytes
                           and canonical_schedule_bytes(run.schedule) == candidate_schedule_bytes
                           and run.invariant_id == invariant["id"]
                           and run.step_id == first_runtime.step_id for run in runs)
                predicate = (
                    same and _signature(first.result) == expected
                    and first.invariant_id == invariant["id"]
                    and first.step_id == first_runtime.step_id
                    and _linked(first.result, first.schedule)
                    and dict(first.result.manifest.input_resource_hashes) == dict(candidate_resources.hashes())
                    and first.result.manifest.scenario_hash == scenario_hash
                    and first.schedule.scenario_hash == scenario_hash
                )
                if not predicate:
                    rejected += 1
                    rejection_reasons.append("FAILURE_SIGNATURE_OR_DETERMINISM_MISMATCH")
                    continue
                if not _replay(first, scenario, candidate, budget):
                    if budget.stop is not None:
                        stop_reason, pass_completed = budget.stop, False
                        break
                    rejected += 1
                    rejection_reasons.append("CANDIDATE_EXACT_REPLAY_FAILED")
                    continue
                current, current_result, current_schedule = candidate, first.result, first.schedule
                removals.append((path, original_index))
                accepted += 1
                changed = True
                break
            if not pass_completed or changed:
                break
        if not pass_completed:
            break
        if changed:
            continue
        complete = True
        break

    identity = MappingProxyType({
        "actor": failure.actor, "code": failure.code,
        "invariant_expression": _freeze(_thaw(invariant["check"])),
        "invariant_id": invariant["id"], "selection_ordinal": failure.selection_ordinal,
        "step_id": first_runtime.step_id,
    })
    outcome = _outcome(
        request, stop_reason, status="REDUCED" if removals else "NO_REDUCTION",
        inputs=current, original_size=original_size, paths=eligible, removed=tuple(removals),
        result=current_result, schedule=current_schedule, original_result=original_result,
        original_schedule=original_schedule, budget=budget, evaluations=evaluations,
        accepted=accepted, rejected=rejected, invalid=invalid, reasons=rejection_reasons,
        deterministic=True, replay=True, complete=complete,
    )
    return Engine2InputShrinkOutcome(
        outcome.status, outcome.stop_reason, outcome.original_input_size, outcome.reduced_input_size,
        outcome.original_inputs, outcome.reduced_inputs, outcome.removed, outcome.eligible_input_paths,
        outcome.coordinates, identity, outcome.original_result_hash, outcome.final_result_hash,
        outcome.original_schedule_hash, outcome.final_schedule_hash, outcome.final_result,
        outcome.final_schedule, outcome.candidate_evaluations, outcome.execution_count,
        outcome.accepted_count, outcome.rejected_count, outcome.invalid_count,
        outcome.rejection_reasons, outcome.determinism_verified, outcome.replay_verified,
        outcome.complete_final_pass, outcome.minimality,
    )


__all__ = (
    "Engine2InputShrinkError", "Engine2InputShrinkOutcome", "Engine2InputShrinkRequest",
    "FAILURE_PRESERVATION_LEVEL", "MAX_CANDIDATE_EVALUATIONS", "MAX_TOTAL_EXECUTIONS",
    "shrink_failed_inputs",
)
