from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from scenario_engine.ids import LogicalID
from scenario_engine.inspection import (
    EvidenceAvailability, EvidenceValue, InspectionDocument, InspectionSection,
)
from scenario_engine.oracle_assertions import (
    MAX_ASSERTIONS, MAX_ASSERTION_PATH_DEPTH, OracleAssertion, OracleAssertionBoundError,
    OracleAssertionKind as Kind, OracleAssertionOutcome as Outcome, OracleAssertionSchemaError,
    canonical_assertion_bytes, canonical_evaluation_bytes, evaluate_assertions,
)
from scenario_engine.values import MISSING


def document(*sections):
    return InspectionDocument("recorded", tuple(InspectionSection(name, evidence) for name, evidence in sections))


def available(value):
    return EvidenceValue(EvidenceAvailability.AVAILABLE, value)


def assertion(identifier, kind, target, expected=MISSING, parameters=None):
    return OracleAssertion(identifier, kind, target, expected, {} if parameters is None else parameters)


def outcome(doc, item):
    return evaluate_assertions(doc, [item]).results[0]


def test_models_are_immutable_isolated_and_coordinates_stable():
    expected = {"nested": [Decimal("1.20")]}
    parameters = {"safe": [1]}
    item = assertion("stable.id", Kind.EQUAL, "/final_state/a~1b/~0key", expected, parameters)
    expected["nested"].append(2)
    parameters["safe"].append(2)
    assert item.expected["nested"] == (Decimal("1.20"),)
    assert item.parameters["safe"] == (1,)
    with pytest.raises(AttributeError):
        item.target = "/other"
    assert (item.assertion_id, item.kind.value, item.target) == (
        "stable.id", "equal", "/final_state/a~1b/~0key")


def test_repeatability_canonical_bytes_and_declaration_order():
    doc = document(("final_state", available({"b": 2, "a": 1})))
    items = [assertion("second", Kind.EQUAL, "/final_state/b", 2),
             assertion("first", Kind.EQUAL, "/final_state/a", 1)]
    first = evaluate_assertions(doc, items)
    second = evaluate_assertions(doc, items)
    assert [result.assertion_id for result in first.results] == ["second", "first"]
    assert first == second
    assert canonical_assertion_bytes(items) == canonical_assertion_bytes(items)
    assert canonical_evaluation_bytes(first) == canonical_evaluation_bytes(second)


def test_pass_fail_unavailable_and_redacted_are_distinct():
    doc = document(
        ("final_state", available({"value": 3})),
        ("provenance", EvidenceValue(EvidenceAvailability.UNAVAILABLE, reason="not_recorded")),
        ("inputs", EvidenceValue(EvidenceAvailability.REDACTED, reason="secret")),
    )
    results = evaluate_assertions(doc, [
        assertion("pass", Kind.EQUAL, "/final_state/value", 3),
        assertion("fail", Kind.EQUAL, "/final_state/value", 4),
        assertion("missing", Kind.EQUAL, "/provenance/x", 1),
        assertion("redacted", Kind.PRESENT, "/inputs/password"),
    ]).results
    assert [value.outcome for value in results] == [Outcome.PASS, Outcome.FAIL, Outcome.UNAVAILABLE, Outcome.UNAVAILABLE]
    assert results[2].details["availability"] == "unavailable"
    assert results[3].details["availability"] == "redacted"
    assert "observed" not in results[3].details


@pytest.mark.parametrize("left,right", [
    (None, MISSING), (True, 1), (Decimal("1"), 1),
    (LogicalID("00000000-0000-0000-0000-000000000001"), "00000000-0000-0000-0000-000000000001"),
    (datetime(2026, 1, 1, tzinfo=timezone.utc), "2026-01-01"), ({"0": "x"}, ["x"]),
])
def test_typed_equality_does_not_collapse_semantic_types(left, right):
    doc = document(("final_state", available({"value": left})))
    assert outcome(doc, assertion("typed", Kind.EQUAL, "/final_state/value", right)).outcome is Outcome.FAIL


def test_paths_support_root_nested_index_and_rfc6901_escapes():
    doc = document(("final_state", available({"a/b": {"~key": [None]}})))
    assert outcome(doc, assertion("root", Kind.PRESENT, "")).outcome is Outcome.PASS
    assert outcome(doc, assertion("nested", Kind.EQUAL, "/final_state/a~1b/~0key/0", None)).outcome is Outcome.PASS
    assert outcome(doc, assertion("absent", Kind.ABSENT, "/final_state/nope")).outcome is Outcome.PASS
    assert outcome(doc, assertion("present-fail", Kind.PRESENT, "/final_state/nope")).outcome is Outcome.FAIL


def test_count_subsequence_occurrence_and_malformed_declarations():
    doc = document(("history", available([{"kind": "a"}, {"kind": "b"}, {"kind": "a"}])))
    cases = [
        assertion("count", Kind.COUNT, "/history", 3),
        assertion("subsequence", Kind.ORDERED_SUBSEQUENCE, "/history", [{"kind": "a"}, {"kind": "a"}]),
        assertion("occurrence", Kind.OCCURRENCE_COUNT, "/history", 2,
                  {"predicate": {"path": "/kind", "operator": "equal", "expected": "a"}}),
    ]
    assert all(result.outcome is Outcome.PASS for result in evaluate_assertions(doc, cases).results)
    with pytest.raises(OracleAssertionSchemaError, match="nonnegative integer"):
        evaluate_assertions(doc, [assertion("bad-count", Kind.COUNT, "/history", True)])
    with pytest.raises(OracleAssertionSchemaError, match="predicate"):
        evaluate_assertions(doc, [assertion("bad-predicate", Kind.OCCURRENCE_COUNT, "/history", 0)])


def test_transition_and_logical_time_families_pass_and_fail():
    t1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    t2 = datetime(2026, 1, 2, tzinfo=timezone.utc)
    doc = document(("history", available([{"transition": "reserve"}, {"transition": "ship"}])),
                   ("clock", available(t2)))
    items = [
        assertion("occurs-pass", Kind.TRANSITION_OCCURRENCE, "/history", 1, {"transition": "ship"}),
        assertion("occurs-fail", Kind.TRANSITION_OCCURRENCE, "/history", 2, {"transition": "ship"}),
        assertion("order-pass", Kind.TRANSITION_ORDER, "/history", ["reserve", "ship"]),
        assertion("order-fail", Kind.TRANSITION_ORDER, "/history", ["ship", "reserve"]),
        assertion("time-pass", Kind.LOGICAL_TIME, "/clock", t1, {"operator": "gt"}),
        assertion("time-fail", Kind.LOGICAL_TIME, "/clock", t2, {"operator": "lt"}),
    ]
    assert [result.outcome for result in evaluate_assertions(doc, items).results] == [
        Outcome.PASS, Outcome.FAIL, Outcome.PASS, Outcome.FAIL, Outcome.PASS, Outcome.FAIL]


def test_multiple_assertions_are_independent_and_duplicate_ids_rejected():
    doc = document(("final_state", available({"x": 1})))
    first = assertion("a", Kind.EQUAL, "/final_state/x", 2)
    second = assertion("b", Kind.EQUAL, "/final_state/x", 1)
    assert [item.outcome for item in evaluate_assertions(doc, [first, second]).results] == [Outcome.FAIL, Outcome.PASS]
    with pytest.raises(OracleAssertionSchemaError, match="unique"):
        evaluate_assertions(doc, [first, assertion("a", Kind.PRESENT, "/final_state")])


def test_bounds_exact_and_one_over_for_count_depth_and_bytes():
    doc = document(("final_state", available({})))
    exact = [assertion(f"a{i}", Kind.PRESENT, "/final_state") for i in range(MAX_ASSERTIONS)]
    assert len(evaluate_assertions(doc, exact).results) == MAX_ASSERTIONS
    with pytest.raises(OracleAssertionBoundError, match="exceeds"):
        evaluate_assertions(doc, exact + [assertion("over", Kind.PRESENT, "/final_state")])
    assertion("depth", Kind.PRESENT, "/" + "/".join("a" for _ in range(MAX_ASSERTION_PATH_DEPTH)))
    with pytest.raises(OracleAssertionBoundError, match="path"):
        assertion("deep", Kind.PRESENT, "/" + "/".join("a" for _ in range(MAX_ASSERTION_PATH_DEPTH + 1)))
    with pytest.raises(OracleAssertionBoundError, match="canonical assertion"):
        assertion("bytes", Kind.EQUAL, "/final_state", "x" * (1024 * 1024))


def test_phase25_nested_redaction_marker_cannot_be_bypassed():
    doc = document(("input_values", available({"password": {
        "availability": "redacted", "reason": "configured_secret_key"}})))
    result = outcome(doc, assertion("secret", Kind.EQUAL, "/input_values/password", "guess"))
    assert result.outcome is Outcome.UNAVAILABLE
    assert result.details == {"availability": "redacted", "reason": "configured_secret_key"}


def test_scenario_result_is_inspected_without_mutating_bytes_or_rerunning(monkeypatch):
    from scenario_engine import compile_document, parse_yaml, run_scenario
    import scenario_engine.dsl.runtime as runtime

    source = """dsl_version: 1
scenario: assertion_result
clock: {start: '2026-01-01T00:00:00Z'}
initial_state: {count: 1}
steps:
  - id: finish
    write: {count: {$literal: 1}}
    transition: null
"""
    result = run_scenario(compile_document(parse_yaml(source)), root_seed="seed")
    before = result.to_json_bytes()
    monkeypatch.setattr(runtime, "_execute", lambda *args, **kwargs: pytest.fail("scenario was rerun"))
    evaluated = evaluate_assertions(result, [assertion("state", Kind.EQUAL, "/final_state/count", 1)])
    assert evaluated.results[0].outcome is Outcome.PASS
    assert result.to_json_bytes() == before


def test_source_is_pure_static_transform():
    from pathlib import Path

    source = "\n".join(path.read_text() for path in sorted(
        (Path(__file__).parents[1] / "src/scenario_engine/oracle_assertions").glob("*.py")))
    forbidden = ("requests", "urllib", "socket", "subprocess", "multiprocessing", "importlib", "pkgutil",
                 "entry_points", "environ", "getenv", "time.time", "datetime.now", "random", "secrets",
                 "open(", "Path(", "eval(", "exec(", "compile(", "__import__", "pickle", "runner.run", "replay")
    assert not [token for token in forbidden if token in source]
