"""Ordered explanation records derived exclusively from recorded v1 evidence."""

from __future__ import annotations

from typing import Any, Mapping

from scenario_engine.result import ScenarioResult
from scenario_engine.engine2 import Engine2Result
from scenario_engine.schedule import ScheduleArtifact
from scenario_engine.suite import ArtifactOrigin, ArtifactReadModel

from .errors import UnsupportedInspectionTargetError
from .models import (
    ACTOR_EXPLANATION_SCHEMA_VERSION, EvidenceAvailability, ExplanationRecord,
    MAX_EXPLANATION_RECORDS,
)
from .redaction import redact_mapping, validate_redacted_keys


def explain_result(target: ScenarioResult | ArtifactReadModel | Engine2Result, *,
                   schedule: ScheduleArtifact | None = None,
                   actor: str | None = None) -> tuple[ExplanationRecord, ...]:
    if isinstance(target, Engine2Result):
        return _explain_engine2(target, schedule=schedule, actor=actor)
    if schedule is not None or actor is not None:
        raise UnsupportedInspectionTargetError("schedule and actor filters require Engine2Result")
    if isinstance(target, ScenarioResult):
        value = target.normalized()
    elif isinstance(target, ArtifactReadModel) and target.origin is ArtifactOrigin.V1_RESULT:
        value = target.payload
    else:
        raise UnsupportedInspectionTargetError("explain_result requires ScenarioResult or v1 result read model")
    # Explanation details are consumer-visible projections of recorded state.
    # Redact only this detached projection, preserving canonical evidence.
    value = redact_mapping(value, validate_redacted_keys(None))
    scenario_id = value["scenario_id"]
    result: list[ExplanationRecord] = []
    for index, history in enumerate(value["history"]):
        address = history.get("address")
        result.append(ExplanationRecord(
            kind="committed_transition", path=f"/history/{index}", execution_address=address,
            subject_id=str(history.get("transition") or address or scenario_id), outcome="committed",
            details={key: history[key] for key in (
                "timestamp", "transition", "pre", "post", "patch", "faults_applied", "artifacts"
            ) if key in history},
        ))
    for index, artifact in enumerate(value["artifacts"]):
        result.append(ExplanationRecord(
            kind="emitted_artifact", path=f"/artifacts/{index}", execution_address=artifact.get("address"),
            subject_id=str(artifact.get("name") or artifact.get("id") or index), outcome="emitted",
            details={key: artifact[key] for key in sorted(artifact) if key != "address"},
        ))
    provenance = value.get("provenance")
    if provenance is not None:
        for index, record in enumerate(provenance):
            result.append(_provenance(record, index, scenario_id))
    result.append(ExplanationRecord(
        kind="branch_repeat_evidence", path=None, execution_address=None,
        subject_id=scenario_id, outcome="unavailable", details={"reason": "not_unambiguously_recorded"},
        availability=EvidenceAvailability.UNAVAILABLE,
    ))
    if len(result) > MAX_EXPLANATION_RECORDS:
        from .errors import InspectionBoundError
        raise InspectionBoundError(f"explanation exceeds {MAX_EXPLANATION_RECORDS} records")
    return tuple(result)


def _explain_engine2(target: Engine2Result, *, schedule: ScheduleArtifact | None,
                     actor: str | None) -> tuple[ExplanationRecord, ...]:
    if actor is not None and actor not in {item["actor"] for item in target.actors}:
        raise UnsupportedInspectionTargetError("actor filter is not declared by result evidence")
    if schedule is not None and (schedule.schedule_hash != target.schedule_reference.schedule_hash or
                                 schedule.scenario_hash != target.manifest.scenario_hash):
        raise UnsupportedInspectionTargetError("schedule does not match result evidence")
    value = redact_mapping(target.payload(), validate_redacted_keys(None))
    records: list[ExplanationRecord] = []
    selections = {item.committed_history_length: item for item in schedule.records
                  if item.outcome == "COMMITTED"} if schedule is not None else {}
    for index, history in enumerate(value["history"]):
        if actor is not None and history["actor"] != actor:
            continue
        selection = selections.get(index)
        details = {key: history[key] for key in (
            "actor", "timestamp", "transition", "pre", "post", "patch", "faults_applied", "artifacts"
        )}
        details["global_committed_history_index"] = index
        if selection is not None:
            details["schedule_selection"] = {
                "logical_clock": selection.logical_clock, "ready_actors": selection.ready_actors,
                "selection_ordinal": selection.selection_ordinal,
            }
        records.append(ExplanationRecord(
            "committed_transition", f"/history/{index}", history["address"], history["address"],
            "committed", details, schema_version=ACTOR_EXPLANATION_SCHEMA_VERSION,
        ))
    if schedule is not None:
        for selection in schedule.records:
            if selection.outcome != "FAILED" or (actor is not None and selection.selected_actor != actor):
                continue
            records.append(ExplanationRecord(
                "attempted_selection", f"/schedule/records/{selection.selection_ordinal}",
                selection.selected_actor, selection.selected_actor, "failed",
                {"committed_history_length": selection.committed_history_length,
                 "logical_clock": selection.logical_clock, "ready_actors": selection.ready_actors,
                 "selection_ordinal": selection.selection_ordinal,
                 "statement": "selection did not commit a transition"},
                schema_version=ACTOR_EXPLANATION_SCHEMA_VERSION,
            ))
    records.append(ExplanationRecord(
        "terminal_classification", None, None, target.scenario_id, target.classification.lower(),
        {"failure": value["failure"], "schedule_context": "available" if schedule else "unavailable"},
        schema_version=ACTOR_EXPLANATION_SCHEMA_VERSION,
    ))
    if len(records) > MAX_EXPLANATION_RECORDS:
        from .errors import InspectionBoundError
        raise InspectionBoundError(f"explanation exceeds {MAX_EXPLANATION_RECORDS} records")
    return tuple(records)


def _provenance(record: Mapping[str, Any], index: int, scenario_id: str) -> ExplanationRecord:
    kind = str(record.get("kind") or "provenance_observation")
    if kind.startswith("oracle"):
        family = "oracle_observation"
    elif "invariant" in kind:
        family = "invariant_observation"
    elif "constraint" in kind:
        family = "constraint_observation"
    elif "fault" in kind:
        family = "applied_fault"
    elif "generated" in kind:
        family = "generated_value"
    else:
        family = "provenance_observation"
    details = dict(record.get("details") or {})
    for key in ("step_id", "hook", "target", "kind"):
        if record.get(key) is not None:
            details[key] = record[key]
    return ExplanationRecord(
        kind=family, path=f"/provenance/{index}", execution_address=record.get("execution_address"),
        subject_id=str(record.get("id") or scenario_id), outcome=str(record.get("outcome") or "recorded"),
        details=details,
    )
