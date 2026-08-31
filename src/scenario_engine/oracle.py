"""Deterministic expected-violation oracle results."""
from dataclasses import dataclass
from typing import Any

class OracleError(ValueError): pass
class OracleMismatchError(OracleError):
    def __init__(self, evaluation):
        self.evaluation = evaluation
        super().__init__("oracle mismatch: " + ", ".join(evaluation.report.missing_expected_violations + evaluation.report.unexpected_violations))

@dataclass(frozen=True, slots=True)
class OracleReport:
    observed_constraint_violations: tuple[str, ...]
    observed_invariant_violations: tuple[str, ...]
    expected_constraint_violations: tuple[str, ...]
    expected_invariant_violations: tuple[str, ...]
    unexpected_violations: tuple[str, ...]
    missing_expected_violations: tuple[str, ...]
    applied_fault_ids: tuple[str, ...]
    strict_unexpected_effective: bool
    passed: bool

@dataclass(frozen=True, slots=True)
class OracleEvaluation:
    manifest: Any
    result: Any
    report: OracleReport
    provenance: Any
