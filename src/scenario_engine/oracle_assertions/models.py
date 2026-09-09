"""Immutable models for bounded assertions over recorded evidence."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from scenario_engine.inspection.models import freeze_semantic
from scenario_engine.values import MISSING, canonical_bytes

from .errors import OracleAssertionBoundError, OracleAssertionSchemaError


ORACLE_ASSERTION_SCHEMA_VERSION = "oracle.assertion/1"
ORACLE_EVALUATION_SCHEMA_VERSION = "oracle.evaluation/1"
MAX_ASSERTIONS = 1_000
MAX_ASSERTION_PATH_DEPTH = 64
MAX_ASSERTION_BYTES = 1 * 1024 * 1024
MAX_ASSERTION_SCAN_RECORDS = 100_000


class OracleAssertionKind(str, Enum):
    EQUAL = "equal"
    NOT_EQUAL = "not_equal"
    PRESENT = "present"
    ABSENT = "absent"
    COUNT = "count"
    ORDERED_SUBSEQUENCE = "ordered_subsequence"
    OCCURRENCE_COUNT = "occurrence_count"
    TRANSITION_OCCURRENCE = "transition_occurrence"
    TRANSITION_ORDER = "transition_order"
    LOGICAL_TIME = "logical_time"


class OracleAssertionOutcome(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    UNAVAILABLE = "unavailable"


def _validate_pointer(value: str) -> None:
    if not isinstance(value, str):
        raise OracleAssertionSchemaError("target must be an RFC 6901 JSON Pointer")
    if value and not value.startswith("/"):
        raise OracleAssertionSchemaError("target must be an RFC 6901 JSON Pointer")
    tokens = value.split("/")[1:] if value else ()
    if len(tokens) > MAX_ASSERTION_PATH_DEPTH:
        raise OracleAssertionBoundError(f"assertion path exceeds {MAX_ASSERTION_PATH_DEPTH} tokens")
    for token in tokens:
        index = 0
        while index < len(token):
            if token[index] == "~":
                if index + 1 == len(token) or token[index + 1] not in "01":
                    raise OracleAssertionSchemaError("target contains an invalid RFC 6901 escape")
                index += 1
            index += 1


@dataclass(frozen=True, slots=True)
class OracleAssertion:
    """One stable assertion declaration; list position remains semantic ordering."""

    assertion_id: str
    kind: OracleAssertionKind
    target: str
    expected: Any = MISSING
    parameters: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = ORACLE_ASSERTION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != ORACLE_ASSERTION_SCHEMA_VERSION:
            raise OracleAssertionSchemaError(f"unsupported assertion schema: {self.schema_version}")
        if not isinstance(self.assertion_id, str) or not self.assertion_id or len(self.assertion_id) > 128:
            raise OracleAssertionSchemaError("assertion_id must contain 1 to 128 characters")
        if not all(character.isascii() and (character.isalnum() or character in "._-") for character in self.assertion_id):
            raise OracleAssertionSchemaError("assertion_id must be portable ASCII")
        if not isinstance(self.kind, OracleAssertionKind):
            raise OracleAssertionSchemaError("kind must be OracleAssertionKind")
        _validate_pointer(self.target)
        try:
            expected = freeze_semantic(self.expected)
            parameters = freeze_semantic(self.parameters)
        except OracleAssertionBoundError:
            raise
        except Exception:
            raise OracleAssertionSchemaError("assertion contains an invalid semantic value") from None
        if not isinstance(parameters, Mapping):
            raise OracleAssertionSchemaError("parameters must be a mapping")
        object.__setattr__(self, "expected", expected)
        object.__setattr__(self, "parameters", parameters)
        if len(canonical_bytes({"expected": expected, "parameters": parameters})) > MAX_ASSERTION_BYTES:
            raise OracleAssertionBoundError(f"canonical assertion exceeds {MAX_ASSERTION_BYTES} bytes")


@dataclass(frozen=True, slots=True)
class OracleAssertionResult:
    assertion_id: str
    kind: OracleAssertionKind
    target: str
    outcome: OracleAssertionOutcome
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.outcome, OracleAssertionOutcome):
            raise OracleAssertionSchemaError("outcome must be OracleAssertionOutcome")
        frozen = freeze_semantic(self.details)
        if not isinstance(frozen, Mapping):
            raise OracleAssertionSchemaError("result details must be a mapping")
        object.__setattr__(self, "details", frozen)


@dataclass(frozen=True, slots=True)
class OracleAssertionEvaluation:
    target_kind: str
    results: tuple[OracleAssertionResult, ...]
    schema_version: str = ORACLE_EVALUATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != ORACLE_EVALUATION_SCHEMA_VERSION:
            raise OracleAssertionSchemaError(f"unsupported evaluation schema: {self.schema_version}")
        if not isinstance(self.target_kind, str) or not self.target_kind:
            raise OracleAssertionSchemaError("target_kind must be nonempty")
        values = tuple(self.results)
        if len(values) > MAX_ASSERTIONS:
            raise OracleAssertionBoundError(f"evaluation exceeds {MAX_ASSERTIONS} assertions")
        if not all(isinstance(value, OracleAssertionResult) for value in values):
            raise OracleAssertionSchemaError("results must contain OracleAssertionResult values")
        object.__setattr__(self, "results", values)
