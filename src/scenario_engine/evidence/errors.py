"""Typed failures for the declarative evidence bundle contract."""

from scenario_engine.errors import ScenarioEngineError


class EvidenceContractError(ScenarioEngineError, ValueError):
    """An evidence model violates the canonical bundle contract."""

    code = "evidence.contract_invalid"


class EvidenceBoundError(EvidenceContractError):
    """An intrinsic evidence-model resource bound was exceeded."""

    code = "evidence.bound_exceeded"


class EvidenceSerializationError(EvidenceContractError):
    """An evidence model cannot be represented canonically."""

    code = "evidence.serialization_invalid"


class EvidenceValidationError(ScenarioEngineError, ValueError):
    """A bounded, non-executing evidence bundle validation failed."""

    code = "evidence.validation_invalid"


class EvidenceIndexError(EvidenceValidationError):
    """An evidence bundle index is not valid canonical JSON."""

    code = "evidence.index_invalid"


class EvidenceFilesystemError(EvidenceValidationError):
    """An evidence path or filesystem object is unsafe or unreadable."""

    code = "evidence.filesystem_invalid"


class EvidenceIntegrityError(EvidenceValidationError):
    """Physical evidence bytes do not match their declared metadata."""

    code = "evidence.integrity_invalid"


class EvidenceValidationBoundError(EvidenceValidationError):
    """A physical reader/validator resource bound was exceeded."""

    code = "evidence.validation_bound_exceeded"
