"""Canonical semantic representation for validated Phase 0.1 DSL documents."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any, Mapping

from .values import normalize

if TYPE_CHECKING:
    from .dsl.models import CompiledScenario, ScenarioDocument, StepDocument


_SEMANTIC_WRAPPERS = {"$decimal", "$datetime", "$duration", "$missing"}


def _canonical_node(value: Any) -> Any:
    if isinstance(value, Mapping):
        if len(value) == 1 and next(iter(value)) in _SEMANTIC_WRAPPERS:
            from .dsl.parser import decode_semantic_value

            return decode_semantic_value(value)
        if len(value) == 1 and "$literal" in value:
            from .dsl.parser import decode_semantic_value

            return {"$literal": decode_semantic_value(value["$literal"])}
        return {key: _canonical_node(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_canonical_node(item) for item in value]
    return value


def _step_payload(step: StepDocument) -> Mapping[str, Any]:
    payload = {
        "advance": step.advance,
        "derive": _canonical_node(step.derive),
        "emit": _canonical_node(step.emit),
        "generate": _canonical_node(step.generate),
        "id": step.step_id,
        "transition": step.transition,
        "write": _canonical_node(step.write),
    }
    if step.call is not None: payload["call"] = _canonical_node(step.call)
    if step.branch is not None: payload["branch"] = _canonical_node(step.branch)
    if step.repeat is not None: payload["repeat"] = _canonical_node(step.repeat)
    return payload


def _document(value: str | ScenarioDocument | CompiledScenario) -> ScenarioDocument:
    from .dsl.models import CompiledScenario, ScenarioDocument
    from .dsl.parser import parse_yaml

    if isinstance(value, str):
        return parse_yaml(value)
    if isinstance(value, CompiledScenario):
        return value.document
    if isinstance(value, ScenarioDocument):
        return value
    raise TypeError("scenario must be YAML text, ScenarioDocument, or CompiledScenario")


def canonical_scenario_payload(
    scenario: str | ScenarioDocument | CompiledScenario,
) -> Mapping[str, Any]:
    """Return the JSON-compatible semantic payload of a validated scenario."""
    document = _document(scenario)
    payload = {
        "clock": {"start": document.reference_clock_start},
        "dsl_version": document.dsl_version,
        "initial_state": document.initial_state,
        "scenario": document.scenario_id,
        "steps": [_step_payload(step) for step in document.steps],
    }
    if document.resources:
        payload["resources"] = _canonical_node(document.resources)
    if document.validators:
        payload["validators"] = _canonical_node(document.validators)
    if document.constraints:
        payload["constraints"] = _canonical_node(document.constraints)
    if document.subflows:
        payload["subflows"] = {
            name: {"steps": [_step_payload(step) for step in document.subflows[name]]}
            for name in sorted(document.subflows)
        }
    if document.invariants:
        payload["invariants"] = _canonical_node(document.invariants)
    if document.faults:
        payload["faults"] = _canonical_node(document.faults)
    if document.oracle is not None:
        payload["oracle"] = _canonical_node(document.oracle)
    return normalize(payload)


def canonical_scenario_bytes(
    scenario: str | ScenarioDocument | CompiledScenario,
) -> bytes:
    return json.dumps(
        canonical_scenario_payload(scenario),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def canonical_scenario_hash(
    scenario: str | ScenarioDocument | CompiledScenario,
) -> str:
    return hashlib.sha256(canonical_scenario_bytes(scenario)).hexdigest()
