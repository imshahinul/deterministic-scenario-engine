"""Canonical UTF-8 JSON serialization for semantic diff documents."""

from __future__ import annotations

import json
from typing import Any, Mapping

from scenario_engine.values import normalize

from .errors import DiffBoundError
from .models import MAX_DIFF_BYTES, DiffRecord, SemanticDiff


def _record(value: DiffRecord) -> Mapping[str, Any]:
    result: dict[str, Any] = {
        "left_present": value.left_present,
        "left_type": value.left_type,
        "operation": value.operation.value,
        "path": value.path,
        "right_present": value.right_present,
        "right_type": value.right_type,
    }
    if value.left_present:
        result["left_value"] = value.left_value
    if value.right_present:
        result["right_value"] = value.right_value
    return result


def diff_to_jsonable(document: SemanticDiff) -> Mapping[str, Any]:
    if not isinstance(document, SemanticDiff):
        raise TypeError("document must be SemanticDiff")
    return normalize({
        "comparison_kind": document.comparison_kind,
        "equal": document.equal,
        "omitted_count": document.omitted_count,
        "records": [_record(record) for record in document.records],
        "schema_version": document.schema_version,
        "truncated": document.truncated,
    })


def canonical_diff_bytes(document: SemanticDiff) -> bytes:
    data = json.dumps(
        diff_to_jsonable(document), ensure_ascii=False, separators=(",", ":"), sort_keys=True,
    ).encode("utf-8")
    if len(data) > MAX_DIFF_BYTES:
        raise DiffBoundError(f"canonical diff exceeds {MAX_DIFF_BYTES} bytes")
    return data


def canonical_diff_text(document: SemanticDiff) -> str:
    return canonical_diff_bytes(document).decode("utf-8")
