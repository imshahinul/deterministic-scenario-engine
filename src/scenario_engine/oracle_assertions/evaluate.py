"""Pure bounded assertion evaluation over Phase 2.5 evidence."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from scenario_engine.inspection import EvidenceAvailability, InspectionDocument, inspect
from scenario_engine.inspection.errors import UnsupportedInspectionTargetError
from scenario_engine.values import MISSING, normalize

from .errors import (
    OracleAssertionBoundError, OracleAssertionSchemaError, OracleAssertionTargetError,
    UnsupportedOracleAssertionError,
)
from .models import (
    MAX_ASSERTIONS, MAX_ASSERTION_SCAN_RECORDS, OracleAssertion, OracleAssertionEvaluation,
    OracleAssertionKind, OracleAssertionOutcome, OracleAssertionResult,
)


_ABSENT = object()
_REDACTION_KEYS = frozenset({"availability", "reason"})


def _tokens(pointer: str) -> tuple[str, ...]:
    if not pointer:
        return ()
    return tuple(token.replace("~1", "/").replace("~0", "~") for token in pointer[1:].split("/"))


def _semantic_equal(left: Any, right: Any) -> bool:
    normalized_left, normalized_right = normalize(left), normalize(right)
    if isinstance(normalized_left, bool) != isinstance(normalized_right, bool):
        return False
    return normalized_left == normalized_right


def _availability_marker(value: Any) -> bool:
    return (
        isinstance(value, Mapping)
        and set(value) == _REDACTION_KEYS
        and value.get("availability") in {
            EvidenceAvailability.UNAVAILABLE.value, EvidenceAvailability.REDACTED.value,
        }
        and isinstance(value.get("reason"), str)
    )


def _document_root(document: InspectionDocument) -> Mapping[str, Any]:
    result: dict[str, Any] = {}
    for section in document.sections:
        evidence = section.evidence
        if evidence.availability is EvidenceAvailability.AVAILABLE:
            result[section.name] = evidence.value
        else:
            result[section.name] = {
                "availability": evidence.availability.value,
                "reason": evidence.reason,
            }
    return result


def _resolve(document: InspectionDocument, pointer: str) -> tuple[EvidenceAvailability, Any, str | None]:
    current: Any = _document_root(document)
    for position, token in enumerate(_tokens(pointer)):
        if _availability_marker(current):
            availability = EvidenceAvailability(current["availability"])
            return availability, _ABSENT, current["reason"]
        if isinstance(current, Mapping):
            if token not in current:
                return EvidenceAvailability.AVAILABLE, _ABSENT, None
            current = current[token]
        elif isinstance(current, (list, tuple)):
            if not token.isdigit() or (len(token) > 1 and token.startswith("0")):
                return EvidenceAvailability.AVAILABLE, _ABSENT, None
            index = int(token)
            if index >= len(current):
                return EvidenceAvailability.AVAILABLE, _ABSENT, None
            current = current[index]
        else:
            return EvidenceAvailability.AVAILABLE, _ABSENT, None
        if _availability_marker(current):
            availability = EvidenceAvailability(current["availability"])
            return availability, _ABSENT, current["reason"]
    if _availability_marker(current):
        availability = EvidenceAvailability(current["availability"])
        return availability, _ABSENT, current["reason"]
    return EvidenceAvailability.AVAILABLE, current, None


def _details(observed: Any = MISSING, expected: Any = MISSING, **extra: Any) -> Mapping[str, Any]:
    value: dict[str, Any] = dict(extra)
    if observed is not MISSING:
        value["observed"] = observed
    if expected is not MISSING:
        value["expected"] = expected
    return value


def _result(assertion: OracleAssertion, passed: bool, details: Mapping[str, Any]) -> OracleAssertionResult:
    return OracleAssertionResult(assertion.assertion_id, assertion.kind, assertion.target,
                                 OracleAssertionOutcome.PASS if passed else OracleAssertionOutcome.FAIL, details)


def _integer_expected(assertion: OracleAssertion) -> int:
    value = assertion.expected
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise OracleAssertionSchemaError(f"{assertion.kind.value} expected must be a nonnegative integer")
    return value


def _subsequence(observed: Sequence[Any], expected: Sequence[Any]) -> bool:
    position = 0
    for item in observed:
        if position < len(expected) and _semantic_equal(item, expected[position]):
            position += 1
    return position == len(expected)


def _bounded_sequence(value: Any, message: str) -> Sequence[Any]:
    if not isinstance(value, (list, tuple)):
        raise OracleAssertionSchemaError(message)
    if len(value) > MAX_ASSERTION_SCAN_RECORDS:
        raise OracleAssertionBoundError(f"assertion scan exceeds {MAX_ASSERTION_SCAN_RECORDS} records")
    return value


def _normalized_datetime(value: Any) -> str | None:
    normalized = normalize(value)
    if (isinstance(normalized, Mapping) and normalized.get("$type") == "datetime"
            and set(normalized) == {"$type", "value"} and isinstance(normalized["value"], str)):
        return normalized["value"]
    return None


def _predicate_matches(record: Any, predicate: Mapping[str, Any]) -> bool:
    path = predicate.get("path", "")
    operator = predicate.get("operator")
    if not isinstance(path, str) or (path and not path.startswith("/")):
        raise OracleAssertionSchemaError("predicate path must be an RFC 6901 JSON Pointer")
    current = record
    for token in _tokens(path):
        if isinstance(current, Mapping) and token in current:
            current = current[token]
        elif isinstance(current, (list, tuple)) and token.isdigit() and int(token) < len(current):
            current = current[int(token)]
        else:
            current = _ABSENT
            break
    if _availability_marker(current):
        return False
    if operator == "present":
        return current is not _ABSENT
    if operator == "absent":
        return current is _ABSENT
    if operator == "equal" and "expected" in predicate:
        return current is not _ABSENT and _semantic_equal(current, predicate["expected"])
    raise OracleAssertionSchemaError("predicate operator must be present, absent, or equal")


def _evaluate_available(assertion: OracleAssertion, observed: Any) -> OracleAssertionResult:
    kind = assertion.kind
    if kind is OracleAssertionKind.PRESENT:
        return _result(assertion, observed is not _ABSENT, _details(present=observed is not _ABSENT))
    if kind is OracleAssertionKind.ABSENT:
        return _result(assertion, observed is _ABSENT, _details(present=observed is not _ABSENT))
    if observed is _ABSENT:
        return _result(assertion, False, _details(expected=assertion.expected, present=False))
    if kind in (OracleAssertionKind.EQUAL, OracleAssertionKind.NOT_EQUAL):
        equal = _semantic_equal(observed, assertion.expected)
        return _result(assertion, equal if kind is OracleAssertionKind.EQUAL else not equal,
                       _details(observed, assertion.expected))
    if kind is OracleAssertionKind.COUNT:
        if not isinstance(observed, (Mapping, list, tuple)):
            raise OracleAssertionSchemaError("count target must be a mapping or sequence")
        expected = _integer_expected(assertion)
        return _result(assertion, len(observed) == expected, _details(len(observed), expected))
    if kind is OracleAssertionKind.ORDERED_SUBSEQUENCE:
        observed_sequence = _bounded_sequence(
            observed, "ordered_subsequence requires sequence target and expected value")
        if not isinstance(assertion.expected, (list, tuple)):
            raise OracleAssertionSchemaError("ordered_subsequence requires sequence target and expected value")
        return _result(assertion, _subsequence(observed_sequence, assertion.expected),
                       _details(observed, assertion.expected))
    if kind is OracleAssertionKind.OCCURRENCE_COUNT:
        observed_sequence = _bounded_sequence(observed, "occurrence_count target must be a sequence")
        predicate = assertion.parameters.get("predicate")
        if not isinstance(predicate, Mapping):
            raise OracleAssertionSchemaError("occurrence_count requires a predicate mapping")
        expected = _integer_expected(assertion)
        count = sum(_predicate_matches(record, predicate) for record in observed_sequence)
        return _result(assertion, count == expected, _details(count, expected))
    if kind is OracleAssertionKind.TRANSITION_OCCURRENCE:
        observed_sequence = _bounded_sequence(observed, "transition_occurrence target must be history sequence")
        transition = assertion.parameters.get("transition")
        if not isinstance(transition, str) or not transition:
            raise OracleAssertionSchemaError("transition_occurrence requires a transition parameter")
        expected = _integer_expected(assertion)
        count = sum(isinstance(record, Mapping) and _semantic_equal(record.get("transition", MISSING), transition)
                    for record in observed_sequence)
        return _result(assertion, count == expected, _details(count, expected, transition=transition))
    if kind is OracleAssertionKind.TRANSITION_ORDER:
        observed_sequence = _bounded_sequence(
            observed, "transition_order requires history sequence and expected sequence")
        if not isinstance(assertion.expected, (list, tuple)):
            raise OracleAssertionSchemaError("transition_order requires history sequence and expected sequence")
        transitions = tuple(record["transition"] for record in observed_sequence
                            if isinstance(record, Mapping) and record.get("transition") is not None)
        return _result(assertion, _subsequence(transitions, assertion.expected),
                       _details(transitions, assertion.expected))
    if kind is OracleAssertionKind.LOGICAL_TIME:
        operator = assertion.parameters.get("operator", "equal")
        observed_time = _normalized_datetime(observed)
        expected_time = _normalized_datetime(assertion.expected)
        if observed_time is None or expected_time is None:
            raise OracleAssertionSchemaError("logical_time requires datetime target and expected value")
        if operator not in {"equal", "lt", "lte", "gt", "gte"}:
            raise OracleAssertionSchemaError("logical_time operator must be equal, lt, lte, gt, or gte")
        comparisons = {"equal": observed_time == expected_time, "lt": observed_time < expected_time,
                       "lte": observed_time <= expected_time, "gt": observed_time > expected_time,
                       "gte": observed_time >= expected_time}
        return _result(assertion, comparisons[operator], _details(observed, assertion.expected, operator=operator))
    raise UnsupportedOracleAssertionError("unsupported oracle assertion kind")


def evaluate_assertions(target: Any, assertions: Sequence[OracleAssertion]) -> OracleAssertionEvaluation:
    """Evaluate declarations in their semantic declaration order without executing a scenario."""
    values = tuple(assertions)
    if len(values) > MAX_ASSERTIONS:
        raise OracleAssertionBoundError(f"evaluation exceeds {MAX_ASSERTIONS} assertions")
    if not all(isinstance(value, OracleAssertion) for value in values):
        raise OracleAssertionSchemaError("assertions must contain OracleAssertion values")
    identifiers = [value.assertion_id for value in values]
    if len(identifiers) != len(set(identifiers)):
        raise OracleAssertionSchemaError("assertion IDs must be unique")
    try:
        document = target if isinstance(target, InspectionDocument) else inspect(target)
    except UnsupportedInspectionTargetError:
        raise OracleAssertionTargetError("unsupported recorded-evidence target") from None
    results: list[OracleAssertionResult] = []
    for assertion in values:
        availability, observed, reason = _resolve(document, assertion.target)
        if availability is not EvidenceAvailability.AVAILABLE:
            results.append(OracleAssertionResult(
                assertion.assertion_id, assertion.kind, assertion.target, OracleAssertionOutcome.UNAVAILABLE,
                {"availability": availability.value, "reason": reason},
            ))
        else:
            results.append(_evaluate_available(assertion, observed))
    return OracleAssertionEvaluation(document.target_kind, tuple(results))


evaluate = evaluate_assertions
