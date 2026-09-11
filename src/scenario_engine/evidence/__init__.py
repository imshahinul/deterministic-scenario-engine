"""Public Phase 3 evidence bundle contract subpackage."""

from .canonical import (
    canonical_evidence_bytes,
    canonical_evidence_text,
    evidence_bundle_hash,
)
from .errors import (
    EvidenceBoundError,
    EvidenceContractError,
    EvidenceFilesystemError,
    EvidenceIndexError,
    EvidenceIntegrityError,
    EvidenceSerializationError,
    EvidenceValidationBoundError,
    EvidenceValidationError,
)
from .models import (
    DEFAULT_AGGREGATE_BUNDLE_BYTES,
    EVIDENCE_BUNDLE_SCHEMA_VERSION,
    EVIDENCE_ENTRY_SCHEMA_VERSION,
    EVIDENCE_PROVENANCE_SCHEMA_VERSION,
    EVIDENCE_RELATIONSHIP_SCHEMA_VERSION,
    MAX_AGGREGATE_BUNDLE_BYTES,
    MAX_ARTIFACT_BYTES,
    MAX_BUNDLE_ENTRIES,
    MAX_BUNDLE_INDEX_BYTES,
    MAX_BUNDLE_PATH_DEPTH,
    MAX_BUNDLE_RELATIONSHIPS,
    EvidenceBundle,
    EvidenceEntry,
    EvidenceProvenance,
    EvidenceRelationship,
    EvidenceType,
)
from .read import MAX_BUNDLE_INDEX_DEPTH, read_evidence_bundle


__all__ = (
    "DEFAULT_AGGREGATE_BUNDLE_BYTES",
    "EVIDENCE_BUNDLE_SCHEMA_VERSION",
    "EVIDENCE_ENTRY_SCHEMA_VERSION",
    "EVIDENCE_PROVENANCE_SCHEMA_VERSION",
    "EVIDENCE_RELATIONSHIP_SCHEMA_VERSION",
    "MAX_AGGREGATE_BUNDLE_BYTES",
    "MAX_ARTIFACT_BYTES",
    "MAX_BUNDLE_ENTRIES",
    "MAX_BUNDLE_INDEX_BYTES",
    "MAX_BUNDLE_INDEX_DEPTH",
    "MAX_BUNDLE_PATH_DEPTH",
    "MAX_BUNDLE_RELATIONSHIPS",
    "EvidenceBoundError",
    "EvidenceBundle",
    "EvidenceContractError",
    "EvidenceEntry",
    "EvidenceFilesystemError",
    "EvidenceIndexError",
    "EvidenceIntegrityError",
    "EvidenceProvenance",
    "EvidenceRelationship",
    "EvidenceSerializationError",
    "EvidenceType",
    "EvidenceValidationBoundError",
    "EvidenceValidationError",
    "canonical_evidence_bytes",
    "canonical_evidence_text",
    "evidence_bundle_hash",
    "read_evidence_bundle",
)
