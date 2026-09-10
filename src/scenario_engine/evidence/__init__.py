"""Public Phase 3 evidence bundle contract subpackage."""

from .canonical import (
    canonical_evidence_bytes,
    canonical_evidence_text,
    evidence_bundle_hash,
)
from .errors import EvidenceBoundError, EvidenceContractError, EvidenceSerializationError
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
    "MAX_BUNDLE_PATH_DEPTH",
    "MAX_BUNDLE_RELATIONSHIPS",
    "EvidenceBoundError",
    "EvidenceBundle",
    "EvidenceContractError",
    "EvidenceEntry",
    "EvidenceProvenance",
    "EvidenceRelationship",
    "EvidenceSerializationError",
    "EvidenceType",
    "canonical_evidence_bytes",
    "canonical_evidence_text",
    "evidence_bundle_hash",
)
