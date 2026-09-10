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
