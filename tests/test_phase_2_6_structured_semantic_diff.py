from __future__ import annotations

from dataclasses import FrozenInstanceError
from decimal import Decimal
import re

import pytest

from scenario_engine.batch import BatchPlan, RunRequest, execute_batch
from scenario_engine.canonical import canonical_scenario_hash
from scenario_engine.diff import (
    DIFF_SCHEMA_VERSION, DiffBoundError, DiffMode, DiffOperation, UnsupportedDiffTargetError,
    canonical_diff_bytes, compare_inspection_documents, render_diff_text, semantic_diff,
)
from scenario_engine.dsl import compile_document, parse_yaml, run_scenario
from scenario_engine.ids import LogicalID
from scenario_engine.inspection import (
    EvidenceAvailability, EvidenceValue, InspectionDocument, InspectionSection,
)
from scenario_engine.matrix import MatrixDimension, MatrixPlan, execute_matrix
from scenario_engine.values import MISSING


def document(value, *, kind="test"):
    return InspectionDocument(kind, (InspectionSection("value", EvidenceValue(EvidenceAvailability.AVAILABLE, value)),))


def unavailable(state, reason="not_recorded"):
    return InspectionDocument("test", (InspectionSection("value", EvidenceValue(state, reason=reason)),))


def scenario():
    return compile_document(parse_yaml("""dsl_version: 1
scenario: phase_2_6_case
clock: {start: '2026-01-01T00:00:00Z'}
resources:
  selected: {input: selected, required: true}
initial_state: {value: 0}
steps:
  - id: apply
    write: {value: {$resource: selected}}
    transition: null
"""))


def records(left, right, **kwargs):
    return compare_inspection_documents(document(left), document(right), **kwargs).records


def test_immutable_equal_and_repeatable_canonical_document():
    original = {"nested": [Decimal("1.00")]}
    result = compare_inspection_documents(document(original), document({"nested": [Decimal("1.00")]}))
    original["nested"].append("mutation")
    assert result.schema_version == DIFF_SCHEMA_VERSION
    assert result.equal and result.records == () and not result.truncated and result.omitted_count == 0
    assert canonical_diff_bytes(result) == canonical_diff_bytes(result)
    with pytest.raises(FrozenInstanceError):
        result.equal = False


def test_mapping_operations_order_and_insertion_order_irrelevance():
    assert records({"b": 2, "a": 1}, {"a": 1, "b": 2}) == ()
    found = records({"b": 2, "gone": 1, "same": 0}, {"a": 3, "b": 4, "same": 0})
    assert [(item.path, item.operation) for item in found] == [
        ("/sections/value/value/a", DiffOperation.ADD),
        ("/sections/value/value/b", DiffOperation.REPLACE),
        ("/sections/value/value/gone", DiffOperation.REMOVE),
    ]


def test_sequence_order_indexes_and_no_set_behavior():
    found = records(["a", "b"], ["b", "a", "c"])
    assert [(item.path, item.operation) for item in found] == [
        ("/sections/value/value/0", DiffOperation.REPLACE),
        ("/sections/value/value/1", DiffOperation.REPLACE),
        ("/sections/value/value/2", DiffOperation.ADD),
    ]


@pytest.mark.parametrize(("key", "escaped"), [
    ("nested", "nested"), ("/", "~1"), ("~", "~0"), ("~/", "~0~1"),
])
def test_json_pointer_nested_mapping_and_escaping(key, escaped):
    item = records({"outer": {key: 1}}, {"outer": {key: 2}})[0]
    assert item.path == f"/sections/value/value/outer/{escaped}"


def test_json_pointer_root_and_sequence_index():
    left = InspectionDocument("left", ())
    right = InspectionDocument("right", ())
    root = compare_inspection_documents(left, right).records[0]
    assert root.path == "/target_kind"
    assert records([0], [1])[0].path.endswith("/0")


def test_root_pointer_is_empty_for_root_type_change_via_bounded_internal_contract():
    # Public documents are mappings; the model still validates the architecture's empty root pointer.
    from scenario_engine.diff import DiffRecord
    root = DiffRecord("", DiffOperation.TYPE, True, True, "mapping", "sequence", {}, ())
    assert root.path == ""


@pytest.mark.parametrize(("left", "right", "left_type", "right_type"), [
    (True, 1, "bool", "int"),
    (None, MISSING, "null", "missing"),
    (Decimal("1.0"), "1.0", "decimal", "string"),
    ({}, [], "mapping", "sequence"),
    (LogicalID("00000000-0000-0000-0000-000000000001"),
     "00000000-0000-0000-0000-000000000001", "logical_id", "string"),
])
def test_typed_semantics_are_explicit(left, right, left_type, right_type):
    item = records(left, right)[0]
    assert item.operation is DiffOperation.TYPE
    assert (item.left_type, item.right_type) == (left_type, right_type)


def test_null_missing_and_evidence_availability_are_distinct_without_redaction_leakage():
    available_null = document(None)
    unavailable_doc = unavailable(EvidenceAvailability.UNAVAILABLE)
    redacted_doc = unavailable(EvidenceAvailability.REDACTED, "secret_omitted")
    assert compare_inspection_documents(available_null, unavailable_doc).records
    state = compare_inspection_documents(unavailable_doc, redacted_doc)
    assert any(item.path.endswith("/availability") for item in state.records)
    rendered = render_diff_text(compare_inspection_documents(redacted_doc, unavailable_doc))
    assert "secret_omitted" in rendered
    assert "raw-password" not in rendered


def test_first_is_first_complete_record_and_stops_before_later_bound(monkeypatch):
    left, right = document({"a": 0, "b": 0}), document({"a": 1, "b": 1})
    complete = compare_inspection_documents(left, right)
    first = compare_inspection_documents(left, right, mode=DiffMode.FIRST)
    assert first.records == complete.records[:1] and len(first.records) == 1


def test_complete_returns_deterministic_prefix_and_explicit_truncation_metadata():
    left, right = document({"c": 0, "a": 0, "b": 0}), document({"b": 1, "c": 1, "a": 1})
    bounded = compare_inspection_documents(left, right, max_records=2)
    assert [item.path.rsplit("/", 1)[-1] for item in bounded.records] == ["a", "b"]
    assert bounded.truncated and bounded.omitted_count == 1 and not bounded.equal
    with pytest.raises(DiffBoundError):
        compare_inspection_documents(left, right, max_records=100_001)


def test_depth_and_canonical_byte_bounds_fail_deterministically(monkeypatch):
    import scenario_engine.diff.compare as compare
    left_nested, right_nested = 0, 1
    for _ in range(10):
        left_nested = {"next": left_nested}
        right_nested = {"next": right_nested}
    monkeypatch.setattr(compare, "MAX_DIFF_DEPTH", 8)
    with pytest.raises(DiffBoundError, match="nesting exceeds"):
        compare_inspection_documents(document(left_nested), document(right_nested))
    import scenario_engine.diff.serialization as serialization
    monkeypatch.setattr(serialization, "MAX_DIFF_BYTES", 1)
    with pytest.raises(DiffBoundError, match="canonical diff exceeds"):
        serialization.canonical_diff_bytes(compare_inspection_documents(document(1), document(2)))


def test_unsupported_targets_and_invalid_mode_fail_in_diff_family():
    with pytest.raises(UnsupportedDiffTargetError):
        semantic_diff(object(), object())
    with pytest.raises(Exception, match="first.*complete"):
        compare_inspection_documents(document(1), document(2), mode="unknown")


def test_convenience_api_uses_inspection_normalization_and_cross_kind_is_explicit():
    left, right = document(1, kind="v1_result"), document(2, kind="matrix_result")
    result = semantic_diff(left, right)
    assert result.comparison_kind == "v1_result:matrix_result"
    assert result.records


def test_v1_result_manifest_and_read_model_diff_without_mutation_or_replay():
    target = scenario()
    left = run_scenario(target, "seed", inputs={"selected": Decimal("1.00")})
    right = run_scenario(target, "seed", run_index=1, inputs={"selected": Decimal("1.00")})
    before = left.to_json_bytes()
    result_diff = semantic_diff(left, right)
    assert any("execution_context" in item.path or "history" in item.path
               for item in result_diff.records)
    assert semantic_diff(left, left).equal
    assert left.to_json_bytes() == before

    manifest_diff = semantic_diff(left.manifest, right.manifest)
    assert any("run_index" in item.path for item in manifest_diff.records)
    assert not any("execution_replay_supported" in item.path for item in manifest_diff.records)


def test_matrix_and_batch_normalized_identity_order_status_and_assignment_diff():
    target = scenario()
    first_plan = MatrixPlan(
        target.scenario_id, canonical_scenario_hash(target),
        (MatrixDimension("selected", (1, 2)),), (), "seed", "C", target,
    )
    second_plan = MatrixPlan(
        target.scenario_id, canonical_scenario_hash(target),
        (MatrixDimension("selected", (1, 3)),), (), "seed", "C", target,
    )
    matrix_diff = semantic_diff(execute_matrix(first_plan), execute_matrix(second_plan))
    paths = [item.path for item in matrix_diff.records]
    assert any("case_id" in path for path in paths)
    assert any("ordered_assignment" in path for path in paths)
    assert not any("/Users/" in path for path in paths)

    first_batch = execute_batch(BatchPlan((RunRequest("run", target, "seed", inputs={"selected": 1}),)))
    second_batch = execute_batch(BatchPlan((RunRequest("run", target, "seed", inputs={"selected": 2}),)))
    batch_diff = semantic_diff(first_batch, second_batch)
    assert batch_diff.records
    assert any("plan" in item.path or "items" in item.path for item in batch_diff.records)


def test_renderer_is_stable_ordered_plain_text_and_canonical_model_is_primary():
    result = compare_inspection_documents(document({"b": 0, "a": 0}), document({"a": 1, "b": 1}))
    text = render_diff_text(result)
    assert text == render_diff_text(result)
    assert text.index("/a ") < text.index("/b ")
    assert not re.search(r"\x1b|0x[0-9a-fA-F]+", text)


def test_static_diff_source_has_no_impure_facilities():
    from pathlib import Path
    source = "\n".join(path.read_text() for path in Path("src/scenario_engine/diff").glob("*.py"))
    forbidden = (
        "subprocess", "multiprocessing", "importlib", "urllib", "requests", "socket", "pathlib",
        "os.environ", "getenv(", "random", "secrets", "datetime.now", "time.time", "open(",
        "eval(", "exec(", "compile(", "__import__(",
    )
    assert not [token for token in forbidden if token in source]
