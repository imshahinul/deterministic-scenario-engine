"""Internal finite Engine 1/Engine 2 compatibility dispatch policy."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


COMPATIBILITY2_CONTRACT = "scenario.compatibility/2"


class CompatibilityClassification(str, Enum):
    SUPPORTED_EXACT = "SUPPORTED_EXACT"
    SUPPORTED_LEGACY_OPERATION = "SUPPORTED_LEGACY_OPERATION"
    UNSUPPORTED_CROSS_MAJOR = "UNSUPPORTED_CROSS_MAJOR"
    UNKNOWN_CONTRACT = "UNKNOWN_CONTRACT"
    UNKNOWN_VERSION = "UNKNOWN_VERSION"
    INCOMPLETE_COORDINATES = "INCOMPLETE_COORDINATES"


@dataclass(frozen=True, slots=True)
class CompatibilityDecision:
    classification: CompatibilityClassification
    operation: str
    contract: str = COMPATIBILITY2_CONTRACT


_KNOWN_RESULTS = {"scenario.result/1": (1, "1.0.0"), "scenario.result/2": (2, "2.0.0")}


def classify_engine_contract(
    *, dsl_version: int | None, engine_version: str | None,
    result_contract: str | None, operation: str,
) -> CompatibilityDecision:
    """Classify without executing, migrating, or silently promoting evidence."""
    if operation not in ("execute", "replay", "inspect"):
        return CompatibilityDecision(CompatibilityClassification.UNKNOWN_CONTRACT, operation)
    if dsl_version is None or engine_version is None or result_contract is None:
        return CompatibilityDecision(CompatibilityClassification.INCOMPLETE_COORDINATES, operation)
    expected = _KNOWN_RESULTS.get(result_contract)
    if expected is None:
        return CompatibilityDecision(CompatibilityClassification.UNKNOWN_CONTRACT, operation)
    if (dsl_version, engine_version) == expected:
        return CompatibilityDecision(CompatibilityClassification.SUPPORTED_EXACT, operation)
    if result_contract == "scenario.result/1" and operation == "inspect" and engine_version == "2.0.0":
        return CompatibilityDecision(CompatibilityClassification.SUPPORTED_LEGACY_OPERATION, operation)
    if dsl_version not in (1, 2) or engine_version not in ("1.0.0", "2.0.0"):
        return CompatibilityDecision(CompatibilityClassification.UNKNOWN_VERSION, operation)
    return CompatibilityDecision(CompatibilityClassification.UNSUPPORTED_CROSS_MAJOR, operation)
