"""Immutable public machine models for Inspect + Explain."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from scenario_engine.values import normalize

from .errors import InspectionBoundError, InspectionSchemaError


INSPECTION_SCHEMA_VERSION = "inspection.document/1"
EXPLANATION_SCHEMA_VERSION = "inspection.explanation/1"
MAX_INSPECTION_SECTIONS = 32
MAX_INSPECTION_RECORDS = 100_000
MAX_EXPLANATION_RECORDS = 100_000
MAX_INSPECTION_BYTES = 256 * 1024 * 1024
MAX_INSPECTION_DEPTH = 64


class EvidenceAvailability(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    REDACTED = "redacted"


def freeze_semantic(value: Any, *, _depth: int = 0, _counter: list[int] | None = None) -> Any:
    """Validate and defensively freeze an established engine semantic value."""
    if _depth > MAX_INSPECTION_DEPTH:
        raise InspectionBoundError(f"inspection nesting exceeds {MAX_INSPECTION_DEPTH}")
    counter = [0] if _counter is None else _counter
    counter[0] += 1
    if counter[0] > MAX_INSPECTION_RECORDS:
        raise InspectionBoundError(f"inspection traversal exceeds {MAX_INSPECTION_RECORDS} values")
    try:
        normalize(value)
    except (TypeError, ValueError):
        raise InspectionSchemaError("inspection contains an invalid semantic value") from None
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise InspectionSchemaError("inspection mappings require string keys")
        return MappingProxyType({
            key: freeze_semantic(value[key], _depth=_depth + 1, _counter=counter)
            for key in sorted(value)
        })
    if isinstance(value, (list, tuple)):
        return tuple(freeze_semantic(item, _depth=_depth + 1, _counter=counter) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class EvidenceValue:
    """A value whose unavailable/redacted state cannot be confused with null or MISSING."""

    availability: EvidenceAvailability
    value: Any = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.availability, EvidenceAvailability):
            raise InspectionSchemaError("availability must be EvidenceAvailability")
        if self.availability is EvidenceAvailability.AVAILABLE:
            object.__setattr__(self, "value", freeze_semantic(self.value))
            if self.reason is not None:
                raise InspectionSchemaError("available evidence cannot have a reason")
        else:
            if self.value is not None:
                raise InspectionSchemaError("unavailable or redacted evidence cannot contain a value")
            if not isinstance(self.reason, str) or not self.reason:
                raise InspectionSchemaError("unavailable or redacted evidence requires a stable reason")


@dataclass(frozen=True, slots=True)
class InspectionSection:
    """One explicitly named, ordered category of recorded evidence."""

    name: str
    evidence: EvidenceValue

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise InspectionSchemaError("section name must be nonempty")
        if not isinstance(self.evidence, EvidenceValue):
            raise InspectionSchemaError("section evidence must be EvidenceValue")


@dataclass(frozen=True, slots=True)
class InspectionDocument:
    """A versioned path-free immutable normalized observation."""

    target_kind: str
    sections: tuple[InspectionSection, ...]
    schema_version: str = INSPECTION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != INSPECTION_SCHEMA_VERSION:
            raise InspectionSchemaError(f"unsupported inspection schema: {self.schema_version}")
        if not isinstance(self.target_kind, str) or not self.target_kind:
            raise InspectionSchemaError("target_kind must be nonempty")
        sections = tuple(self.sections)
        if len(sections) > MAX_INSPECTION_SECTIONS:
            raise InspectionBoundError(f"inspection exceeds {MAX_INSPECTION_SECTIONS} sections")
        if not all(isinstance(item, InspectionSection) for item in sections):
            raise InspectionSchemaError("sections must contain InspectionSection values")
        names = [item.name for item in sections]
        if len(names) != len(set(names)):
            raise InspectionSchemaError("inspection contains a duplicate section")
        object.__setattr__(self, "sections", sections)

    def section(self, name: str) -> InspectionSection:
        for section in self.sections:
            if section.name == name:
                return section
        raise KeyError(name)


@dataclass(frozen=True, slots=True)
class ExplanationRecord:
    """One ordered structured causal observation from recorded evidence only."""

    kind: str
    path: str | None
    execution_address: str | None
    subject_id: str
    outcome: str
    details: Mapping[str, Any] = field(default_factory=dict)
    availability: EvidenceAvailability = EvidenceAvailability.AVAILABLE
    schema_version: str = EXPLANATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != EXPLANATION_SCHEMA_VERSION:
            raise InspectionSchemaError(f"unsupported explanation schema: {self.schema_version}")
        for name in ("kind", "subject_id", "outcome"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise InspectionSchemaError(f"{name} must be nonempty")
        for name in ("path", "execution_address"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value):
                raise InspectionSchemaError(f"{name} must be null or nonempty")
        if not isinstance(self.availability, EvidenceAvailability):
            raise InspectionSchemaError("availability must be EvidenceAvailability")
        frozen = freeze_semantic(self.details)
        if not isinstance(frozen, Mapping):
            raise InspectionSchemaError("details must be a mapping")
        object.__setattr__(self, "details", frozen)
