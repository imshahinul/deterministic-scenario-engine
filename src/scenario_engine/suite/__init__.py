"""Public Phase 2.1 suite and read-contract submodule."""

from .errors import (
    ArtifactBoundError,
    ArtifactReadError,
    SuiteContractError,
    SuiteSerializationError,
    UnsupportedArtifactVersionError,
    UnsupportedReplayContractError,
)
from .models import (
    BATCH_CONTRACT_VERSION,
    BATCH_SCHEMA_VERSION,
    MATRIX_CONTRACT_VERSION,
    MATRIX_SCHEMA_VERSION,
    READ_SCHEMA_VERSION,
    RUN_SCHEMA_VERSION,
    SUITE_SCHEMA_VERSION,
    ArtifactOrigin,
    ArtifactReadModel,
    ArtifactReference,
    BatchItemResult,
    BatchManifest,
    BatchResultEnvelope,
    BatchStatus,
    BoundsMetadata,
    CompatibilityRecord,
    DomainPackRecord,
    ExecutionContext,
    ExecutionReplaySupport,
    FailureRecord,
    MatrixCase,
    MatrixCaseResultEnvelope,
    MatrixManifest,
    MatrixResultEnvelope,
    ReadSupport,
    RunManifestEnvelope,
    SuiteManifest,
)
from .read import (
    MAX_ARTIFACT_BYTES,
    MAX_ARTIFACT_COLLECTION_ITEMS,
    MAX_ARTIFACT_DEPTH,
    read_v1_manifest_bytes,
    read_v1_manifest_text,
    read_v1_result_bytes,
    read_v1_result_text,
)
from .serialization import (
    canonical_suite_bytes,
    canonical_suite_text,
    parse_suite_bytes,
    parse_suite_text,
)


__all__ = (
    "ArtifactBoundError", "ArtifactOrigin", "ArtifactReadError", "ArtifactReadModel",
    "ArtifactReference", "BATCH_CONTRACT_VERSION", "BATCH_SCHEMA_VERSION", "BatchItemResult",
    "BatchManifest", "BatchResultEnvelope", "BatchStatus", "BoundsMetadata", "CompatibilityRecord",
    "DomainPackRecord", "ExecutionContext", "ExecutionReplaySupport", "FailureRecord",
    "MATRIX_CONTRACT_VERSION", "MATRIX_SCHEMA_VERSION", "MAX_ARTIFACT_BYTES",
    "MAX_ARTIFACT_COLLECTION_ITEMS", "MAX_ARTIFACT_DEPTH", "MatrixCase",
    "MatrixCaseResultEnvelope", "MatrixManifest", "MatrixResultEnvelope", "READ_SCHEMA_VERSION",
    "RUN_SCHEMA_VERSION", "ReadSupport", "RunManifestEnvelope", "SUITE_SCHEMA_VERSION",
    "SuiteContractError", "SuiteManifest", "SuiteSerializationError", "UnsupportedArtifactVersionError",
    "UnsupportedReplayContractError", "canonical_suite_bytes", "canonical_suite_text",
    "parse_suite_bytes", "parse_suite_text", "read_v1_manifest_bytes", "read_v1_manifest_text",
    "read_v1_result_bytes", "read_v1_result_text",
)
