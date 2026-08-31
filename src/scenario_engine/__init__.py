"""Executable semantic kernel for the Phase 0.1A spike."""

from .address import ExecutionAddress
from .control_flow import MAX_REPEAT_COUNT
from .artifacts import GeneratedArtifact
from .clock import LogicalClock
from .canonical import (
    canonical_scenario_bytes, canonical_scenario_hash, canonical_scenario_payload,
)
from .context import GenerationContext
from .history import HistoryRecord, ScenarioHistory
from .ids import DeterministicIDProvider, LogicalID
from .manifest import (
    ENGINE_VERSION, ReplayCompatibilityError, ReproducibilityManifest,
)
from .result import ScenarioResult
from .rng import DeterministicRNG, IntegerRange
from .runner import CandidateStep, ScenarioRunner, StepSpec
from .state import ScenarioState
from .values import MISSING, canonical_bytes, fingerprint, normalize

__all__ = [
    "CandidateStep", "DeterministicIDProvider", "DeterministicRNG",
    "ExecutionAddress", "GeneratedArtifact", "GenerationContext",
    "HistoryRecord", "IntegerRange", "LogicalClock", "LogicalID", "MISSING",
    "ReplayCompatibilityError", "ReproducibilityManifest", "ScenarioHistory",
    "ScenarioResult", "ScenarioRunner", "ScenarioState", "StepSpec",
    "ENGINE_VERSION", "canonical_bytes", "canonical_scenario_bytes",
    "canonical_scenario_hash", "canonical_scenario_payload", "fingerprint", "normalize",
    "MAX_REPEAT_COUNT",
]
