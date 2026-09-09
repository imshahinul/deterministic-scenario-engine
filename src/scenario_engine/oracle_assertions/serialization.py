"""Canonical UTF-8 JSON for oracle declarations and evaluations."""

from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

from scenario_engine.values import normalize

from .errors import OracleAssertionBoundError, OracleAssertionSchemaError
from .models import (
    MAX_ASSERTIONS, MAX_ASSERTION_BYTES, ORACLE_ASSERTION_SCHEMA_VERSION,
    OracleAssertion, OracleAssertionEvaluation,
)


def assertion_to_jsonable(assertion: OracleAssertion) -> Mapping[str, Any]:
    if not isinstance(assertion, OracleAssertion):
        raise TypeError("assertion must be OracleAssertion")
    return normalize({"assertion_id": assertion.assertion_id, "expected": assertion.expected,
                      "kind": assertion.kind.value, "parameters": assertion.parameters,
                      "schema_version": assertion.schema_version, "target": assertion.target})


def assertions_to_jsonable(assertions: Sequence[OracleAssertion]) -> Mapping[str, Any]:
    values = tuple(assertions)
    if len(values) > MAX_ASSERTIONS:
        raise OracleAssertionBoundError(f"document exceeds {MAX_ASSERTIONS} assertions")
    if not all(isinstance(value, OracleAssertion) for value in values):
        raise OracleAssertionSchemaError("document must contain OracleAssertion values")
    return {"assertions": [assertion_to_jsonable(value) for value in values],
            "schema_version": ORACLE_ASSERTION_SCHEMA_VERSION}


def evaluation_to_jsonable(evaluation: OracleAssertionEvaluation) -> Mapping[str, Any]:
    if not isinstance(evaluation, OracleAssertionEvaluation):
        raise TypeError("evaluation must be OracleAssertionEvaluation")
    return normalize({"results": [{"assertion_id": result.assertion_id, "details": result.details,
                                    "kind": result.kind.value, "outcome": result.outcome.value,
                                    "target": result.target} for result in evaluation.results],
                      "schema_version": evaluation.schema_version, "target_kind": evaluation.target_kind})


def _canonical(value: Any) -> bytes:
    data = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    if len(data) > MAX_ASSERTION_BYTES:
        raise OracleAssertionBoundError(f"canonical assertion document exceeds {MAX_ASSERTION_BYTES} bytes")
    return data


def canonical_assertion_bytes(assertions: OracleAssertion | Sequence[OracleAssertion]) -> bytes:
    values = (assertions,) if isinstance(assertions, OracleAssertion) else assertions
    return _canonical(assertions_to_jsonable(values))


def canonical_assertion_text(assertions: OracleAssertion | Sequence[OracleAssertion]) -> str:
    return canonical_assertion_bytes(assertions).decode("utf-8")


def canonical_evaluation_bytes(evaluation: OracleAssertionEvaluation) -> bytes:
    return _canonical(evaluation_to_jsonable(evaluation))


def canonical_evaluation_text(evaluation: OracleAssertionEvaluation) -> str:
    return canonical_evaluation_bytes(evaluation).decode("utf-8")
