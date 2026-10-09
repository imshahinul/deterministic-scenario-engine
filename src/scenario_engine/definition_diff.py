"""Deterministic structural comparison of validated DSL 1 and DSL 2 definitions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
from typing import Any, Iterable, Mapping

from scenario_engine.canonical import canonical_scenario_hash
from scenario_engine.diagnostics import semantic_address
from scenario_engine.dsl import compile_document
from scenario_engine.dsl.models import ActorDocument, ScenarioDocument, ScenarioDocumentV2, StepDocument
from scenario_engine.values import normalize


DEFINITION_DIFF_CONTRACT = "scenario.definition-diff/1"
ACTOR_DEFINITION_DIFF_CONTRACT = "scenario.definition-diff/2"
MAX_DEFINITION_CHANGES = 100_000


class DefinitionChangeKind(str, Enum):
    ADDED = "ADDED"
    REMOVED = "REMOVED"
    CHANGED = "CHANGED"


@dataclass(frozen=True, slots=True)
class DefinitionChange:
    change_kind: DefinitionChangeKind
    semantic_path: str
    before: Any = None
    after: Any = None

    def to_jsonable(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "change_kind": self.change_kind.value,
            "semantic_path": self.semantic_path,
        }
        if self.change_kind is not DefinitionChangeKind.ADDED:
            value["before"] = normalize(self.before)
        if self.change_kind is not DefinitionChangeKind.REMOVED:
            value["after"] = normalize(self.after)
        return value


@dataclass(frozen=True, slots=True)
class DefinitionDiff:
    left_identity: str
    right_identity: str
    left_hash: str
    right_hash: str
    dsl_version: int
    changes: tuple[DefinitionChange, ...]
    schema: str = DEFINITION_DIFF_CONTRACT

    def to_jsonable(self) -> dict[str, Any]:
        counts = {kind.value: 0 for kind in DefinitionChangeKind}
        for change in self.changes:
            counts[change.change_kind.value] += 1
        return {
            "changes": [change.to_jsonable() for change in self.changes],
            "inputs": {
                "left": {"identity": self.left_identity, "hash": self.left_hash},
                "right": {"identity": self.right_identity, "hash": self.right_hash},
            },
            "schema": self.schema,
            "summary": {"change_count": len(self.changes), "counts": counts},
            "dsl_version": self.dsl_version,
        }

    def to_json_bytes(self) -> bytes:
        return json.dumps(
            self.to_jsonable(), ensure_ascii=False, allow_nan=False,
            sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")


def _address(*components: tuple[str, str]) -> str:
    value = semantic_address(*components, activate_actor=any(kind == "actor" for kind, _ in components))
    if value is None:
        raise ValueError("definition entity cannot be represented by scenario.semantic-address/1")
    return value


def _step_value(step: StepDocument) -> dict[str, Any]:
    value: dict[str, Any] = {
        "advance": step.advance,
        "derive": step.derive,
        "emit": step.emit,
        "generate": step.generate,
        "transition": step.transition,
        "write": step.write,
    }
    if step.call is not None:
        value["call"] = step.call
    if step.branch is not None:
        value["branch"] = step.branch
    if step.repeat is not None:
        value["repeat"] = step.repeat
    return normalize(value)


def _keyed(values: Iterable[Mapping[str, Any]], key: str = "id") -> dict[str, Mapping[str, Any]]:
    return {str(value[key]): value for value in values}


def _record(changes: list[DefinitionChange], path: str, before: Any, after: Any,
            *, before_present: bool = True, after_present: bool = True) -> None:
    normalized_before = normalize(before) if before_present else None
    normalized_after = normalize(after) if after_present else None
    if before_present and after_present and normalized_before == normalized_after:
        return
    if len(changes) >= MAX_DEFINITION_CHANGES:
        raise ValueError(f"definition diff exceeds {MAX_DEFINITION_CHANGES} changes")
    kind = (DefinitionChangeKind.ADDED if not before_present else
            DefinitionChangeKind.REMOVED if not after_present else
            DefinitionChangeKind.CHANGED)
    changes.append(DefinitionChange(kind, path, normalized_before, normalized_after))


def _compare_mapping(changes: list[DefinitionChange], base: tuple[tuple[str, str], ...],
                     kind: str, left: Mapping[str, Any], right: Mapping[str, Any]) -> None:
    for name in sorted(set(left) | set(right)):
        _record(changes, _address(*base, (kind, name)), left.get(name), right.get(name),
                before_present=name in left, after_present=name in right)


def _compare_keyed(changes: list[DefinitionChange], kind: str,
                   left: Iterable[Mapping[str, Any]], right: Iterable[Mapping[str, Any]]) -> None:
    left_by_id, right_by_id = _keyed(left), _keyed(right)
    for name in sorted(set(left_by_id) | set(right_by_id)):
        _record(changes, _address((kind, name)), left_by_id.get(name), right_by_id.get(name),
                before_present=name in left_by_id, after_present=name in right_by_id)


def _compare_steps(changes: list[DefinitionChange], left: tuple[StepDocument, ...],
                   right: tuple[StepDocument, ...],
                   prefix: tuple[tuple[str, str], ...] = ()) -> None:
    left_by_id = {step.step_id: step for step in left}
    right_by_id = {step.step_id: step for step in right}
    for step_id in sorted(set(left_by_id) | set(right_by_id)):
        base = (*prefix, ("step", step_id))
        if step_id not in left_by_id:
            _record(changes, _address(*base), None, _step_value(right_by_id[step_id]), before_present=False)
            continue
        if step_id not in right_by_id:
            _record(changes, _address(*base), _step_value(left_by_id[step_id]), None, after_present=False)
            continue
        before, after = left_by_id[step_id], right_by_id[step_id]
        _compare_mapping(changes, base, "generator", before.generate, after.generate)
        _compare_mapping(changes, base, "derive", before.derive, after.derive)
        _compare_mapping(changes, base, "write", before.write, after.write)
        _record(changes, _address(*base, ("emit", "emissions")), before.emit, after.emit)
        _record(changes, _address(*base, ("transition", "target")), before.transition, after.transition)
        _record(changes, _address(*base, ("x-advance", "duration")), before.advance, after.advance)
        for control in ("call", "branch", "repeat"):
            _record(changes, _address(*base, ("x-control", control)),
                    getattr(before, control), getattr(after, control))


def compare_definitions(left: ScenarioDocument, right: ScenarioDocument) -> DefinitionDiff:
    """Compare two definitions after ordinary parser/compiler validation, without execution."""
    supported = (ScenarioDocument, ScenarioDocumentV2)
    if not isinstance(left, supported) or not isinstance(right, supported):
        raise TypeError("definition diff inputs must be validated scenario document values")
    if type(left) is not type(right):
        raise ValueError("definition diff does not support cross-DSL-major comparison")
    compile_document(left)
    compile_document(right)
    if isinstance(left, ScenarioDocumentV2) and isinstance(right, ScenarioDocumentV2):
        return _compare_actor_definitions(left, right)
    changes: list[DefinitionChange] = []
    _record(changes, _address(("x-definition", "scenario")), left.scenario_id, right.scenario_id)
    _record(changes, _address(("x-definition", "clock")), left.reference_clock_start, right.reference_clock_start)
    _record(changes, _address(("x-definition", "initial-state")), left.initial_state, right.initial_state)
    _compare_mapping(changes, (), "resource", left.resources, right.resources)
    _compare_keyed(changes, "constraint", left.constraints, right.constraints)
    _compare_keyed(changes, "invariant", left.invariants, right.invariants)
    _compare_keyed(changes, "fault", left.faults, right.faults)
    _compare_keyed(changes, "x-validator", left.validators, right.validators)
    _record(changes, _address(("oracle", "expectation")), left.oracle, right.oracle)
    _compare_steps(changes, left.steps, right.steps)
    for subflow in sorted(set(left.subflows) | set(right.subflows)):
        path = _address(("x-subflow", subflow))
        if subflow not in left.subflows:
            _record(changes, path, None, [_step_value(step) for step in right.subflows[subflow]], before_present=False)
        elif subflow not in right.subflows:
            _record(changes, path, [_step_value(step) for step in left.subflows[subflow]], None, after_present=False)
        else:
            _compare_steps(
                changes, left.subflows[subflow], right.subflows[subflow],
                (("x-subflow", subflow),),
            )
    changes.sort(key=lambda change: (change.semantic_path.encode("utf-8"), change.change_kind.value))
    return DefinitionDiff(
        left.scenario_id, right.scenario_id, canonical_scenario_hash(left),
        canonical_scenario_hash(right), left.dsl_version, tuple(changes),
    )


def _actor_value(actor: ActorDocument) -> Mapping[str, Any]:
    return normalize({
        "steps": [_step_value(step) for step in actor.steps],
        "subflows": {name: [_step_value(step) for step in actor.subflows[name]]
                     for name in sorted(actor.subflows)},
    })


def _compare_actor_definitions(left: ScenarioDocumentV2, right: ScenarioDocumentV2) -> DefinitionDiff:
    changes: list[DefinitionChange] = []
    _record(changes, _address(("x-definition", "scenario")), left.scenario_id, right.scenario_id)
    _record(changes, _address(("x-definition", "clock")), left.reference_clock_start, right.reference_clock_start)
    _record(changes, _address(("x-definition", "initial-state")), left.initial_state, right.initial_state)
    _compare_mapping(changes, (), "resource", left.resources, right.resources)
    _compare_keyed(changes, "constraint", left.constraints, right.constraints)
    _compare_keyed(changes, "invariant", left.invariants, right.invariants)
    _compare_keyed(changes, "fault", left.faults, right.faults)
    _compare_keyed(changes, "x-validator", left.validators, right.validators)
    _record(changes, _address(("oracle", "expectation")), left.oracle, right.oracle)
    left_actors = {actor.address: actor for actor in left.actors}
    right_actors = {actor.address: actor for actor in right.actors}
    for address in sorted(set(left_actors) | set(right_actors), key=str.encode):
        actor_id = (left_actors.get(address) or right_actors[address]).actor_id
        base = (("actor", actor_id),)
        if address not in left_actors:
            _record(changes, _address(*base), None, _actor_value(right_actors[address]), before_present=False)
            continue
        if address not in right_actors:
            _record(changes, _address(*base), _actor_value(left_actors[address]), None, after_present=False)
            continue
        before, after = left_actors[address], right_actors[address]
        _compare_steps(changes, before.steps, after.steps, base)
        for subflow in sorted(set(before.subflows) | set(after.subflows)):
            path = _address(*base, ("x-subflow", subflow))
            if subflow not in before.subflows:
                _record(changes, path, None, [_step_value(step) for step in after.subflows[subflow]], before_present=False)
            elif subflow not in after.subflows:
                _record(changes, path, [_step_value(step) for step in before.subflows[subflow]], None, after_present=False)
            else:
                _compare_steps(changes, before.subflows[subflow], after.subflows[subflow],
                               (*base, ("x-subflow", subflow)))
    changes.sort(key=lambda change: (change.semantic_path.encode("utf-8"), change.change_kind.value))
    return DefinitionDiff(left.scenario_id, right.scenario_id, canonical_scenario_hash(left),
                          canonical_scenario_hash(right), 2, tuple(changes),
                          ACTOR_DEFINITION_DIFF_CONTRACT)


def render_definition_diff(diff: DefinitionDiff) -> str:
    lines = [f"scenario definition structural diff: {len(diff.changes)} change(s)"]
    for change in diff.changes:
        lines.append(f"{change.change_kind.value} {change.semantic_path}")
        if change.change_kind is not DefinitionChangeKind.ADDED:
            lines.append("  before: " + json.dumps(normalize(change.before), ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        if change.change_kind is not DefinitionChangeKind.REMOVED:
            lines.append("  after: " + json.dumps(normalize(change.after), ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return "\n".join(lines)


__all__ = [
    "ACTOR_DEFINITION_DIFF_CONTRACT", "DEFINITION_DIFF_CONTRACT", "DefinitionChange", "DefinitionChangeKind",
    "DefinitionDiff", "compare_definitions", "render_definition_diff",
]
