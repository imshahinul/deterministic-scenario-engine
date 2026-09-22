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


class EvidenceExportError(ScenarioEngineError, ValueError):
    """A bounded evidence serialization or export failed."""

    code = "evidence.export_invalid"


class EvidenceExportBoundError(EvidenceExportError):
    """An evidence export exceeded a configured or architectural bound."""

    code = "evidence.export_bound_exceeded"


class EvidenceDestinationError(EvidenceExportError):
    """An evidence export destination is existing or unsafe."""

    code = "evidence.destination_invalid"


class EvidenceSourceIntegrityError(EvidenceExportError):
    """Source evidence bytes do not match their declared identity."""

    code = "evidence.source_integrity_invalid"


class EvidencePublicationError(EvidenceExportError):
    """A complete staged bundle could not be atomically published."""

    code = "evidence.publication_failed"


class EvidenceAdapterError(ScenarioEngineError, ValueError):
    """An explicit evidence adapter operation or contract failed."""

    code = "evidence.adapter_invalid"


class EvidenceAdapterContractError(EvidenceAdapterError, TypeError):
    """An adapter declaration, request, or return violates the contract."""

    code = "evidence.adapter_contract_invalid"


class EvidenceAdapterBoundError(EvidenceAdapterError):
    """Adapter orchestration or canonical receipts exceeded a bound."""

    code = "evidence.adapter_bound_exceeded"


class EvidenceAdapterOrchestrationError(EvidenceAdapterError, RuntimeError):
    """The generic bounded adapter orchestrator itself failed."""

    code = "evidence.adapter_orchestration_failed"
