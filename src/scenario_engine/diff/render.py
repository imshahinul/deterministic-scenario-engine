"""Pure deterministic human rendering downstream of the structured diff model."""

from __future__ import annotations

import json
from typing import Any

from scenario_engine.values import normalize

from .models import SemanticDiff


def _value(value: Any) -> str:
    return json.dumps(normalize(value), ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def render_diff_text(document: SemanticDiff) -> str:
    """Render stable path/operation lines without terminal or environment behavior."""
    if not isinstance(document, SemanticDiff):
        raise TypeError("document must be SemanticDiff")
    header = "equal" if document.equal else "different"
    lines = [f"semantic diff ({document.comparison_kind}): {header}"]
    for record in document.records:
        path = record.path or "<root>"
        left = _value(record.left_value) if record.left_present else "<absent>"
        right = _value(record.right_value) if record.right_present else "<absent>"
        lines.append(
            f"{record.operation.value} {path} "
            f"[{record.left_type or 'absent'} -> {record.right_type or 'absent'}] {left} -> {right}"
        )
    if document.truncated:
        lines.append(f"truncated: {document.omitted_count} difference(s) omitted")
    return "\n".join(lines)
