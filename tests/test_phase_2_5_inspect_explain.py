from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from decimal import Decimal
import json

import pytest

import scenario_engine
from scenario_engine.batch import BatchPlan, RunRequest, execute_batch
from scenario_engine.canonical import canonical_scenario_hash
from scenario_engine.dsl import compile_document, parse_yaml, run_scenario
from scenario_engine.ids import LogicalID
from scenario_engine._version import VERSION
from scenario_engine.inspection import (
    EvidenceAvailability, EvidenceValue, InspectionBoundError, InspectionDocument,
    InspectionSection, MAX_INSPECTION_SECTIONS, canonical_explanation_bytes,
    canonical_inspection_bytes, explain_result, inspect, inspect_batch, inspect_manifest,
    inspect_result,
)
from scenario_engine.matrix import MatrixDimension, MatrixPlan, execute_matrix, expand_matrix
from scenario_engine.suite import read_v1_manifest_bytes, read_v1_result_bytes
from scenario_engine.values import MISSING


def _scenario():
    return compile_document(parse_yaml("""dsl_version: 1
scenario: inspect_case
clock: {start: '2026-01-01T00:00:00Z'}
resources:
  selected: {input: selected, required: true}
initial_state: {value: 0}
steps:
  - id: apply
    write: {value: {$resource: selected}}
    emit:
      - type: evidence
        fields: {value: {$resource: selected}}
    transition: null
"""))


def _result():
    return run_scenario(_scenario(), "seed", inputs={"selected": Decimal("2.50")})


def test_models_are_immutable_defensively_isolated_and_preserve_typed_semantics() -> None:
    source = {"missing": MISSING, "null": None, "bool": True, "int": 1,
              "decimal": Decimal("1.20"), "when": datetime(2026, 1, 1, tzinfo=timezone.utc),
              "id": LogicalID("12345678-1234-5678-9234-567812345678"), "nested": [1]}
    document = InspectionDocument("test", (InspectionSection("values", EvidenceValue(
        EvidenceAvailability.AVAILABLE, source)),))
    source["nested"].append(2)
    assert document.section("values").evidence.value["nested"] == (1,)
    with pytest.raises(FrozenInstanceError):
        document.target_kind = "changed"
    with pytest.raises(TypeError):
        document.section("values").evidence.value["new"] = 1
    encoded = json.loads(canonical_inspection_bytes(document))
    values = encoded["sections"][0]["evidence"]["value"]
    assert values["missing"] == {"$type": "missing"}
    assert values["null"] is None
    assert values["bool"] is True and values["int"] == 1
    assert values["decimal"] == {"$type": "decimal", "value": "1.20"}
    assert values["id"]["$type"] == "logical-id"


def test_result_manifest_and_read_models_are_stable_inspectable_without_replay() -> None:
    result = _result()
    before = result.to_json_bytes()
    result_document = inspect_result(result)
    assert [item.name for item in result_document.sections] == [
        "schema_identity", "scenario_identity", "execution_context", "compatibility",
        "input_resource_hashes", "final_state", "history", "artifacts", "trace",
        "provenance", "oracle", "branch_repeat",
    ]
    assert "value" in result_document.section("final_state").evidence.value
    assert result_document.section("history").evidence.value
    assert result_document.section("artifacts").evidence.value
    assert result_document.section("branch_repeat").evidence.availability is EvidenceAvailability.UNAVAILABLE
    assert result.to_json_bytes() == before

    manifest_document = inspect_manifest(result.manifest)
    compatibility = manifest_document.section("compatibility").evidence.value
    assert compatibility["recorded"]["engine_version"] == "1.0.0"
    assert compatibility["artifact_readable"] is True
    assert compatibility["artifact_inspectable"] is True
    assert compatibility["execution_replay_supported"] is False

    read_result = read_v1_result_bytes(before)
    manifest_bytes = json.dumps(result.manifest.normalized(), sort_keys=True, separators=(",", ":")).encode()
    read_manifest = read_v1_manifest_bytes(manifest_bytes)
    assert inspect(read_result).target_kind == "v1_result"
    assert inspect(read_manifest).target_kind == "v1_manifest"


def test_suite_matrix_and_batch_recorded_evidence_order_and_redaction() -> None:
    target = _scenario()
    matrix = MatrixPlan(
        target.scenario_id, canonical_scenario_hash(target),
        (MatrixDimension("selected", (1, 2, 3)),), (), "matrix-seed", "C", target,
    )
    matrix_document = inspect(execute_matrix(matrix))
    cases = matrix_document.section("cases").evidence.value
    assert [(item["case_id"], item["original_index"]) for item in cases] == [
        (case.case_id, case.case_index) for case in expand_matrix(matrix)
    ]
    assert cases[0]["ordered_assignment"] == (("selected", 1),)
    assert matrix_document.section("plan").evidence.value["raw_cardinality"] == 3

    requests = (
        RunRequest("first", target, "seed", inputs={"selected": 1, "token": "not-a-real-secret"}),
        RunRequest("second", target, "seed", inputs={"selected": 2}),
    )
    plan = BatchPlan(requests)
    default_document = inspect_batch(plan)
    assert default_document.section("input_values").evidence.availability is EvidenceAvailability.REDACTED
    opted_in = inspect_batch(plan, include_input_values=True)
    input_rows = opted_in.section("input_values").evidence.value
    assert input_rows[0]["values"]["selected"] == 1
    assert input_rows[0]["values"]["token"]["availability"] == "redacted"
    assert "not-a-real-secret" not in canonical_inspection_bytes(opted_in).decode()

    execution_document = inspect_batch(execute_batch(plan))
    items = execution_document.section("items").evidence.value
    assert [(item["run_id"], item["plan_position"], item["status"]) for item in items] == [
        ("first", 0, "success"), ("second", 1, "success")
    ]


def test_explanation_is_record_ordered_byte_stable_and_marks_unavailable_evidence() -> None:
    result = _result()
    records = explain_result(result)
    assert records[0].kind == "committed_transition"
    assert any(item.kind == "emitted_artifact" for item in records)
    assert records[-1].kind == "branch_repeat_evidence"
    assert records[-1].availability is EvidenceAvailability.UNAVAILABLE
    assert canonical_explanation_bytes(records) == canonical_explanation_bytes(explain_result(result))
    assert canonical_inspection_bytes(inspect_result(result)) == canonical_inspection_bytes(inspect_result(result))


def test_bounds_are_exact_and_fail_deterministically(monkeypatch) -> None:
    sections = tuple(InspectionSection(str(index), EvidenceValue(EvidenceAvailability.AVAILABLE, index))
                     for index in range(MAX_INSPECTION_SECTIONS))
    assert len(InspectionDocument("bounded", sections).sections) == MAX_INSPECTION_SECTIONS
    with pytest.raises(InspectionBoundError, match="inspection exceeds"):
        InspectionDocument("bounded", sections + (
            InspectionSection("overflow", EvidenceValue(EvidenceAvailability.AVAILABLE, 1)),))


def test_root_api_and_package_version_remain_frozen() -> None:
    assert "inspect_result" not in scenario_engine.__all__
    assert VERSION == "1.0.0"
