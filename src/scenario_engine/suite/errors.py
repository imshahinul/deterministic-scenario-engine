"""Additive errors for suite schemas and non-executing artifact reads."""

from __future__ import annotations

from scenario_engine.errors import ScenarioEngineError
from scenario_engine.manifest import ReplayCompatibilityError


class SuiteContractError(ScenarioEngineError, ValueError):
    """A suite-layer value or serialized contract is invalid."""

    code = "suite.contract_invalid"


class SuiteSerializationError(SuiteContractError):
    """Canonical suite serialization or strict parsing failed."""

    code = "suite.serialization_invalid"


class ArtifactReadError(ScenarioEngineError, ValueError):
    """A bounded, non-executing artifact read failed."""

    code = "artifact.read_invalid"


class ArtifactBoundError(ArtifactReadError):
    """An artifact exceeded a declared read bound."""

    code = "artifact.bound_exceeded"


class UnsupportedArtifactVersionError(ArtifactReadError):
    """An artifact version is not readable by this contract."""

    code = "artifact.version_unsupported"


class UnsupportedReplayContractError(ReplayCompatibilityError):
    """An artifact is readable but its execution contract is unsupported."""

    code = "replay.engine_version_unsupported"

    def __init__(self, recorded_version: str, supported_contracts: tuple[str, ...]) -> None:
        self.recorded_version = recorded_version
        self.supported_contracts = tuple(supported_contracts)
        supported = ",".join(self.supported_contracts) if self.supported_contracts else "none"
        super().__init__(
            f"{self.code}: recorded engine version {recorded_version}; "
            f"supported execution contracts: {supported}"
        )
