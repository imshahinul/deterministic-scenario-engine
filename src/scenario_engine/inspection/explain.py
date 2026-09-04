"""Ordered explanation records derived exclusively from recorded v1 evidence."""

from __future__ import annotations

from typing import Any, Mapping

from scenario_engine.result import ScenarioResult
from scenario_engine.suite import ArtifactOrigin, ArtifactReadModel

from .errors import UnsupportedInspectionTargetError
from .models import EvidenceAvailability, ExplanationRecord, MAX_EXPLANATION_RECORDS


def explain_result(target: ScenarioResult | ArtifactReadModel) -> tuple[ExplanationRecord, ...]:
    if isinstance(target, ScenarioResult):
        value = target.normalized()
    elif isinstance(target, ArtifactReadModel) and target.origin is ArtifactOrigin.V1_RESULT:
        value = target.payload
    else:
        raise UnsupportedInspectionTargetError("explain_result requires ScenarioResult or v1 result read model")
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
