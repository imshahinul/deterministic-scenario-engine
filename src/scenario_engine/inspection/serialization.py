"""Canonical UTF-8 JSON serialization for Phase 2.5 machine models."""

from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

from scenario_engine.values import normalize

from .errors import InspectionBoundError, InspectionSchemaError
from .models import (
    EvidenceAvailability, EvidenceValue, ExplanationRecord, InspectionDocument,
    InspectionSection, MAX_EXPLANATION_RECORDS, MAX_INSPECTION_BYTES,
)


def _evidence(value: EvidenceValue) -> Mapping[str, Any]:
    result: dict[str, Any] = {"availability": value.availability.value}
    if value.availability is EvidenceAvailability.AVAILABLE:
        result["value"] = value.value
    else:
        result["reason"] = value.reason
    return result


def inspection_to_jsonable(document: InspectionDocument) -> Mapping[str, Any]:
    if not isinstance(document, InspectionDocument):
        raise TypeError("document must be InspectionDocument")
    return normalize({
        "schema_version": document.schema_version,
        "target_kind": document.target_kind,
        "sections": [{"name": item.name, "evidence": _evidence(item.evidence)} for item in document.sections],
    })


def explanation_to_jsonable(records: Sequence[ExplanationRecord]) -> Mapping[str, Any]:
    values = tuple(records)
    if len(values) > MAX_EXPLANATION_RECORDS:
        raise InspectionBoundError(f"explanation exceeds {MAX_EXPLANATION_RECORDS} records")
    if not all(isinstance(item, ExplanationRecord) for item in values):
        raise InspectionSchemaError("explanation must contain ExplanationRecord values")
    version = values[0].schema_version if values else "inspection.explanation/1"
    return normalize({
        "schema_version": version,
        "records": [{
            "availability": item.availability.value,
            "details": item.details,
            "execution_address": item.execution_address,
            "kind": item.kind,
            "outcome": item.outcome,
            "path": item.path,
            "subject_id": item.subject_id,
        } for item in values],
    })


def _canonical(value: Any) -> bytes:
    data = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    if len(data) > MAX_INSPECTION_BYTES:
        raise InspectionBoundError(f"canonical inspection exceeds {MAX_INSPECTION_BYTES} bytes")
    return data


def canonical_inspection_bytes(document: InspectionDocument) -> bytes:
    return _canonical(inspection_to_jsonable(document))


def canonical_inspection_text(document: InspectionDocument) -> str:
    return canonical_inspection_bytes(document).decode("utf-8")


def canonical_explanation_bytes(records: Sequence[ExplanationRecord]) -> bytes:
    return _canonical(explanation_to_jsonable(records))


def canonical_explanation_text(records: Sequence[ExplanationRecord]) -> str:
    return canonical_explanation_bytes(records).decode("utf-8")
