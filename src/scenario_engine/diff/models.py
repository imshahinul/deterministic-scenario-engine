"""Immutable public machine models for structured semantic diff."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from scenario_engine.values import normalize

from .errors import DiffBoundError, DiffSchemaError


DIFF_SCHEMA_VERSION = "semantic.diff/1"
DEFAULT_MAX_DIFF_RECORDS = 10_000
HARD_MAX_DIFF_RECORDS = 100_000
MAX_DIFF_DEPTH = 64
MAX_COMPARED_ITEMS = 1_000_000
MAX_DIFF_BYTES = 256 * 1024 * 1024


class DiffMode(str, Enum):
    FIRST = "first"
    COMPLETE = "complete"


class DiffOperation(str, Enum):
    ADD = "add"
    REMOVE = "remove"
    REPLACE = "replace"
    TYPE = "type"


# A descriptive compatibility alias; the frozen wire value remains ``operation``.
DiffKind = DiffOperation


def freeze_diff_value(value: Any, *, _depth: int = 0) -> Any:
    """Defensively freeze a normalized semantic value without changing its type tags."""
    if _depth > MAX_DIFF_DEPTH:
        raise DiffBoundError(f"diff value nesting exceeds {MAX_DIFF_DEPTH}")
    try:
        normalize(value)
    except (TypeError, ValueError):
        raise DiffSchemaError("diff record contains an invalid semantic value") from None
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise DiffSchemaError("diff value mappings require string keys")
        return MappingProxyType({
            key: freeze_diff_value(value[key], _depth=_depth + 1) for key in sorted(value)
        })
    if isinstance(value, (list, tuple)):
        return tuple(freeze_diff_value(item, _depth=_depth + 1) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class DiffRecord:
    """One stable JSON-Pointer-addressed semantic difference."""

    path: str
    operation: DiffOperation
    left_present: bool
    right_present: bool
    left_type: str | None
    right_type: str | None
    left_value: Any = None
    right_value: Any = None

    def __post_init__(self) -> None:
        if not isinstance(self.path, str) or (self.path and not self.path.startswith("/")):
            raise DiffSchemaError("path must be an RFC 6901 JSON Pointer")
        if not isinstance(self.operation, DiffOperation):
            raise DiffSchemaError("operation must be DiffOperation")
        if not isinstance(self.left_present, bool) or not isinstance(self.right_present, bool):
            raise DiffSchemaError("presence flags must be boolean")
        if not self.left_present and (self.left_type is not None or self.left_value is not None):
            raise DiffSchemaError("an absent left side cannot contain type or value")
        if not self.right_present and (self.right_type is not None or self.right_value is not None):
            raise DiffSchemaError("an absent right side cannot contain type or value")
        for side in ("left", "right"):
            if getattr(self, f"{side}_present"):
                semantic_type = getattr(self, f"{side}_type")
                if not isinstance(semantic_type, str) or not semantic_type:
                    raise DiffSchemaError(f"a present {side} side requires a semantic type")
                object.__setattr__(self, f"{side}_value", freeze_diff_value(getattr(self, f"{side}_value")))
        if self.operation is DiffOperation.ADD and (self.left_present or not self.right_present):
            raise DiffSchemaError("add requires only the right side")
        if self.operation is DiffOperation.REMOVE and (not self.left_present or self.right_present):
            raise DiffSchemaError("remove requires only the left side")
        if self.operation in (DiffOperation.REPLACE, DiffOperation.TYPE) and not (
            self.left_present and self.right_present
        ):
            raise DiffSchemaError("replace and type require both sides")


@dataclass(frozen=True, slots=True)
class SemanticDiff:
    """A versioned deterministic ordered semantic comparison result."""

    comparison_kind: str
    equal: bool
    records: tuple[DiffRecord, ...]
    truncated: bool = False
    omitted_count: int = 0
    schema_version: str = DIFF_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != DIFF_SCHEMA_VERSION:
            raise DiffSchemaError(f"unsupported diff schema: {self.schema_version}")
        if not isinstance(self.comparison_kind, str) or not self.comparison_kind:
            raise DiffSchemaError("comparison_kind must be nonempty")
        records = tuple(self.records)
        if len(records) > HARD_MAX_DIFF_RECORDS:
            raise DiffBoundError(f"diff contains more than {HARD_MAX_DIFF_RECORDS} records")
        if not all(isinstance(record, DiffRecord) for record in records):
            raise DiffSchemaError("records must contain DiffRecord values")
        if not isinstance(self.equal, bool) or not isinstance(self.truncated, bool):
            raise DiffSchemaError("equal and truncated must be boolean")
        if not isinstance(self.omitted_count, int) or isinstance(self.omitted_count, bool) or self.omitted_count < 0:
            raise DiffSchemaError("omitted_count must be a nonnegative integer")
        if self.equal != (not records and not self.truncated):
            raise DiffSchemaError("equal is inconsistent with records and truncation")
        if self.truncated != (self.omitted_count > 0):
            raise DiffSchemaError("truncated is inconsistent with omitted_count")
        object.__setattr__(self, "records", records)


DiffDocument = SemanticDiff
