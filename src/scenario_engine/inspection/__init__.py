"""Public Phase 2.5 Inspect + Explain library contract."""

from .errors import (
    ExplanationError, InspectionBoundError, InspectionError, InspectionSchemaError,
    RedactionConfigurationError, UnsupportedInspectionTargetError,
)
from .explain import explain_result
from .inspect import (
    inspect, inspect_batch, inspect_failure, inspect_manifest, inspect_matrix,
    inspect_result, inspect_suite,
)
from .models import (
    EXPLANATION_SCHEMA_VERSION, INSPECTION_SCHEMA_VERSION, MAX_EXPLANATION_RECORDS,
    MAX_INSPECTION_BYTES, MAX_INSPECTION_DEPTH, MAX_INSPECTION_RECORDS,
    MAX_INSPECTION_SECTIONS, EvidenceAvailability, EvidenceValue, ExplanationRecord,
    InspectionDocument, InspectionSection,
)
from .redaction import DEFAULT_SECRET_KEYS
from .serialization import (
    canonical_explanation_bytes, canonical_explanation_text, canonical_inspection_bytes,
    canonical_inspection_text, explanation_to_jsonable, inspection_to_jsonable,
)


__all__ = (
    "DEFAULT_SECRET_KEYS", "EXPLANATION_SCHEMA_VERSION", "EvidenceAvailability", "EvidenceValue",
    "ExplanationError", "ExplanationRecord", "INSPECTION_SCHEMA_VERSION", "InspectionBoundError",
    "InspectionDocument", "InspectionError", "InspectionSchemaError", "InspectionSection",
    "MAX_EXPLANATION_RECORDS", "MAX_INSPECTION_BYTES", "MAX_INSPECTION_DEPTH",
    "MAX_INSPECTION_RECORDS", "MAX_INSPECTION_SECTIONS", "RedactionConfigurationError",
    "UnsupportedInspectionTargetError", "canonical_explanation_bytes", "canonical_explanation_text",
    "canonical_inspection_bytes", "canonical_inspection_text", "explain_result", "explanation_to_jsonable",
    "inspect", "inspect_batch", "inspect_failure", "inspect_manifest", "inspect_matrix", "inspect_result",
    "inspect_suite", "inspection_to_jsonable",
)
