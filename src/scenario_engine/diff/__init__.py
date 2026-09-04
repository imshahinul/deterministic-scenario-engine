"""Public Phase 2.6 structured semantic diff library contract."""

from .compare import compare_inspection_documents, diff, semantic_diff
from .errors import DiffBoundError, DiffError, DiffModeError, DiffSchemaError, UnsupportedDiffTargetError
from .models import (
    DEFAULT_MAX_DIFF_RECORDS, DIFF_SCHEMA_VERSION, HARD_MAX_DIFF_RECORDS, MAX_COMPARED_ITEMS,
    MAX_DIFF_BYTES, MAX_DIFF_DEPTH, DiffDocument, DiffKind, DiffMode, DiffOperation, DiffRecord,
    SemanticDiff,
)
from .render import render_diff_text
from .serialization import canonical_diff_bytes, canonical_diff_text, diff_to_jsonable


__all__ = (
    "DEFAULT_MAX_DIFF_RECORDS", "DIFF_SCHEMA_VERSION", "DiffBoundError", "DiffDocument", "DiffError",
    "DiffKind", "DiffMode", "DiffModeError", "DiffOperation", "DiffRecord", "DiffSchemaError",
    "HARD_MAX_DIFF_RECORDS", "MAX_COMPARED_ITEMS", "MAX_DIFF_BYTES", "MAX_DIFF_DEPTH", "SemanticDiff",
    "UnsupportedDiffTargetError", "canonical_diff_bytes", "canonical_diff_text",
    "compare_inspection_documents", "diff", "diff_to_jsonable", "render_diff_text", "semantic_diff",
)
