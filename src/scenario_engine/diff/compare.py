"""Pure bounded comparison over Phase 2.5 normalized inspection evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from scenario_engine.inspection import InspectionDocument, inspect, inspection_to_jsonable
from scenario_engine.inspection.errors import UnsupportedInspectionTargetError

from .errors import DiffBoundError, DiffModeError, DiffSchemaError, UnsupportedDiffTargetError
from .models import (
    DEFAULT_MAX_DIFF_RECORDS, HARD_MAX_DIFF_RECORDS, MAX_COMPARED_ITEMS, MAX_DIFF_DEPTH,
    DiffMode, DiffOperation, DiffRecord, SemanticDiff,
)


_TYPED_TAGS = {
    "decimal": "decimal", "logical-id": "logical_id", "datetime": "datetime",
    "duration-microseconds": "duration", "missing": "missing",
}


def _pointer(path: str, token: str | int) -> str:
    escaped = str(token).replace("~", "~0").replace("/", "~1")
    return f"{path}/{escaped}"


def _semantic_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, str):
        return "string"
    if isinstance(value, Mapping):
        tag = value.get("$type")
        if isinstance(tag, str) and tag in _TYPED_TAGS and set(value).issubset({"$type", "value"}):
            return _TYPED_TAGS[tag]
        return "mapping"
    if isinstance(value, (list, tuple)):
        return "sequence"
    raise DiffSchemaError("normalized inspection contains an unsupported semantic value")


def _same_scalar(left: Any, right: Any) -> bool:
    return _semantic_type(left) == _semantic_type(right) and left == right


@dataclass(slots=True)
class _Traversal:
    mode: DiffMode
    maximum: int
    records: list[DiffRecord]
    omitted: int = 0
    compared: int = 0
    stopped: bool = False

    def visit(self, left: Any, right: Any, path: str = "", depth: int = 0) -> None:
        if self.stopped:
            return
        if depth > MAX_DIFF_DEPTH:
            raise DiffBoundError(f"diff nesting exceeds {MAX_DIFF_DEPTH}")
        self.compared += 1
        if self.compared > MAX_COMPARED_ITEMS:
            raise DiffBoundError(f"diff traversal exceeds {MAX_COMPARED_ITEMS} values")
        left_type, right_type = _semantic_type(left), _semantic_type(right)
        if left_type != right_type:
            self.emit(path, DiffOperation.TYPE, True, True, left, right)
            return
        if left_type == "mapping":
            left_keys, right_keys = set(left), set(right)
            for key in sorted(left_keys | right_keys):
                child = _pointer(path, key)
                if key not in left:
                    self.emit(child, DiffOperation.ADD, False, True, None, right[key])
                elif key not in right:
                    self.emit(child, DiffOperation.REMOVE, True, False, left[key], None)
                else:
                    self.visit(left[key], right[key], child, depth + 1)
                if self.stopped:
                    return
            return
        if left_type == "sequence":
            common = min(len(left), len(right))
            for index in range(common):
                self.visit(left[index], right[index], _pointer(path, index), depth + 1)
                if self.stopped:
                    return
            for index in range(common, len(left)):
                self.emit(_pointer(path, index), DiffOperation.REMOVE, True, False, left[index], None)
                if self.stopped:
                    return
            for index in range(common, len(right)):
                self.emit(_pointer(path, index), DiffOperation.ADD, False, True, None, right[index])
                if self.stopped:
                    return
            return
        if not _same_scalar(left, right):
            self.emit(path, DiffOperation.REPLACE, True, True, left, right)

    def emit(
        self, path: str, operation: DiffOperation, left_present: bool, right_present: bool,
        left: Any, right: Any,
    ) -> None:
        if len(self.records) < self.maximum:
            self.records.append(DiffRecord(
                path=path, operation=operation,
                left_present=left_present, right_present=right_present,
                left_type=_semantic_type(left) if left_present else None,
                right_type=_semantic_type(right) if right_present else None,
                left_value=left, right_value=right,
            ))
        else:
            self.omitted += 1
        if self.mode is DiffMode.FIRST:
            self.stopped = True


def _mode(value: DiffMode | str) -> DiffMode:
    if isinstance(value, DiffMode):
        return value
    try:
        return DiffMode(value)
    except (TypeError, ValueError):
        raise DiffModeError("mode must be 'first' or 'complete'") from None


def _comparison_value(document: InspectionDocument) -> Mapping[str, Any]:
    """Address uniquely named inspection sections by semantic name, not storage index."""
    serialized = inspection_to_jsonable(document)
    return {
        "schema_version": serialized["schema_version"],
        "target_kind": serialized["target_kind"],
        "sections": {
            section["name"]: section["evidence"] for section in serialized["sections"]
        },
    }


def compare_inspection_documents(
    left: InspectionDocument, right: InspectionDocument, *, mode: DiffMode | str = DiffMode.COMPLETE,
    max_records: int = DEFAULT_MAX_DIFF_RECORDS,
) -> SemanticDiff:
    """Compare two already-normalized Phase 2.5 inspection documents."""
    if not isinstance(left, InspectionDocument) or not isinstance(right, InspectionDocument):
        raise UnsupportedDiffTargetError("comparison requires two InspectionDocument values")
    selected = _mode(mode)
    if not isinstance(max_records, int) or isinstance(max_records, bool) or not 1 <= max_records <= HARD_MAX_DIFF_RECORDS:
        raise DiffBoundError(f"max_records must be between 1 and {HARD_MAX_DIFF_RECORDS}")
    maximum = 1 if selected is DiffMode.FIRST else max_records
    traversal = _Traversal(selected, maximum, [])
    traversal.visit(_comparison_value(left), _comparison_value(right))
    kind = left.target_kind if left.target_kind == right.target_kind else f"{left.target_kind}:{right.target_kind}"
    return SemanticDiff(
        comparison_kind=kind, equal=not traversal.records and not traversal.omitted,
        records=tuple(traversal.records), truncated=traversal.omitted > 0,
        omitted_count=traversal.omitted,
    )


def semantic_diff(
    left: Any, right: Any, *, mode: DiffMode | str = DiffMode.COMPLETE,
    max_records: int = DEFAULT_MAX_DIFF_RECORDS, inspection_options: Mapping[str, Any] | None = None,
) -> SemanticDiff:
    """Inspect supported recorded targets, then compare their normalized evidence."""
    options = {} if inspection_options is None else dict(inspection_options)
    try:
        left_document = left if isinstance(left, InspectionDocument) else inspect(left, **options)
        right_document = right if isinstance(right, InspectionDocument) else inspect(right, **options)
    except UnsupportedInspectionTargetError:
        raise UnsupportedDiffTargetError("unsupported semantic diff target") from None
    except TypeError as error:
        # Invalid options retain a stable diff-family boundary without raw object reprs.
        raise DiffSchemaError(str(error)) from None
    return compare_inspection_documents(left_document, right_document, mode=mode, max_records=max_records)


diff = semantic_diff
