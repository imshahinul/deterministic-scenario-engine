from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from scenario_engine.definition_diff import compare_definitions
from scenario_engine.dsl import parse_yaml
from scenario_engine.engine2 import (
    Engine2EvidenceError, canonical_manifest2_bytes, canonical_result2_bytes,
    execute_engine2, read_result2, validate_engine2,
)
from scenario_engine.impact import ImpactClassification, analyze_impact
from scenario_engine.inspection import (
    canonical_explanation_bytes, canonical_inspection_bytes, explain_result, inspect,
)
from scenario_engine.schedule import canonical_schedule_bytes


ROOT = Path(__file__).parents[1]
BASE = """dsl_version: 2
scenario: analysis
clock: {start: '2026-01-01T00:00:00Z'}
initial_state: {inventory: 0, observed: -1, token: hidden}
actors:
  - id: customer_a
    steps:
      - id: write_inventory
        write: {inventory: {$add: [{$state: inventory}, {$literal: 1}]}}
        advance: {seconds: 1}
        transition: null
  - id: customer_b
    steps:
      - id: read_inventory
        write: {observed: {$state: inventory}}
        transition: null
"""


def invoke(*arguments: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run([sys.executable, "-m", "scenario_engine.cli", *arguments], cwd=ROOT,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
                          env={"PYTHONPATH": str(ROOT / "src")})


def produced(source: str = BASE):
    scenario = validate_engine2(source)
    result, schedule = execute_engine2(scenario, "generation", 7)
    return scenario, result, schedule


def sections(document) -> dict[str, object]:
    return {item.name: item.evidence.value for item in document.sections}


def test_t01_t11_result_manifest_schedule_inspection_and_trust_distinctions() -> None:
    _, result, schedule = produced()
    result_view = inspect(result); manifest_view = inspect(result.manifest); schedule_view = inspect(schedule)
    assert result_view.schema_version == manifest_view.schema_version == schedule_view.schema_version == "inspection.document/2"
    result_sections = sections(result_view)
    assert result_sections["schema_identity"]["contract"] == "scenario.result/2"
    assert result_sections["scenario_identity"]["scenario_canonical_hash"] == result.manifest.scenario_hash
    assert result_sections["scheduler"]["schedule_hash"] == schedule.schedule_hash
    assert result_sections["generation"]["root_seed"] == "generation"
    assert result_sections["history_summary"] == {"global_committed_transition_count": 2}
    assert sum(item["committed_transition_count"] for item in result_sections["actors"]) == 2
    assert result_sections["final_state"]["token"] == {"availability": "redacted", "reason": "configured_secret_key"}
    assert result_sections["final_logical_clock"] == result.final_logical_clock
    assert result_sections["outcome"]["classification"] == "SUCCESS"
    assert result_sections["integrity"] == {
        "canonical_hash_consistent": True, "exact_replay": "not_requested",
        "structurally_valid": True, "verified_contract": "scenario.result/2",
    }
    assert sections(manifest_view)["execution_context"]["schedule_seed"] == 7
    assert sections(schedule_view)["scheduler"]["selection_count"] == 2
    assert [item["selection_ordinal"] for item in sections(schedule_view)["selections"]] == [0, 1]


def test_t05_t13_explanation_global_order_actor_filter_and_determinism() -> None:
    _, result, schedule = produced()
    records = explain_result(result, schedule=schedule)
    committed = [item for item in records if item.kind == "committed_transition"]
    assert [item.details["global_committed_history_index"] for item in committed] == [0, 1]
    assert [item.execution_address for item in committed] == [item["address"] for item in result.history]
    assert all("selection_ordinal" in item.details["schedule_selection"] for item in committed)
    actor = result.history[0]["actor"]
    filtered = [item for item in explain_result(result, schedule=schedule, actor=actor)
                if item.kind == "committed_transition"]
    assert filtered and all(item.details["actor"] == actor for item in filtered)
    assert canonical_explanation_bytes(records) == canonical_explanation_bytes(explain_result(result, schedule=schedule))


def test_t07_t08_failed_selection_is_not_a_fabricated_commit() -> None:
    source = BASE + "invariants:\n  - id: impossible\n    check: {$lte: [{$state: inventory}, {$literal: 0}]}\n"
    scenario = validate_engine2(source)
    for seed in range(50):
        try:
            execute_engine2(scenario, "generation", seed)
        except Exception as error:
            outcome = getattr(error, "internal_outcome", None)
            if outcome is None:
                continue
            from scenario_engine.engine2 import construct_result2
            result = construct_result2(scenario, outcome)
            schedule = outcome.schedule
            assert schedule.records[-1].outcome == "FAILED"
            assert schedule.records[-1].committed_history_length == len(result.history)
            attempts = [item for item in explain_result(result, schedule=schedule)
                        if item.kind == "attempted_selection"]
            assert len(attempts) == 1 and attempts[0].details["selection_ordinal"] == schedule.records[-1].selection_ordinal
            assert len([item for item in explain_result(result, schedule=schedule)
                        if item.kind == "committed_transition"]) == len(result.history)
            return
    pytest.fail("no bounded schedule seed selected the failing writer")


def test_t14_t22_actor_diff_add_remove_modify_control_rename_and_layout() -> None:
    added = BASE.replace("actors:\n", "actors:\n  - id: audit\n    steps:\n      - id: record\n        transition: null\n")
    addition = compare_definitions(parse_yaml(BASE), parse_yaml(added))
    assert addition.schema == "scenario.definition-diff/2"
    assert [(item.change_kind.value, item.semantic_path) for item in addition.changes] == [
        ("ADDED", "scenario:/actor/audit")]
    removal = compare_definitions(parse_yaml(added), parse_yaml(BASE))
    assert any(item.change_kind.value == "REMOVED" and item.semantic_path == "scenario:/actor/audit"
               for item in removal.changes)
    modified = BASE.replace("{$literal: 1}", "{$literal: 2}")
    assert {item.semantic_path for item in compare_definitions(parse_yaml(BASE), parse_yaml(modified)).changes} == {
        "scenario:/actor/customer_a/step/write_inventory/write/inventory"}
    with_step = BASE.replace("        transition: null\n  - id: customer_b",
        "        transition: finish\n      - id: finish\n        transition: null\n  - id: customer_b", 1)
    step_changes = compare_definitions(parse_yaml(BASE), parse_yaml(with_step)).changes
    assert {item.semantic_path for item in step_changes} == {
        "scenario:/actor/customer_a/step/finish",
        "scenario:/actor/customer_a/step/write_inventory/transition/target",
    }
    renamed = BASE.replace("id: customer_a", "id: customer_c", 1)
    rename_changes = compare_definitions(parse_yaml(BASE), parse_yaml(renamed)).changes
    assert {(item.change_kind.value, item.semantic_path) for item in rename_changes} == {
        ("REMOVED", "scenario:/actor/customer_a"), ("ADDED", "scenario:/actor/customer_c")}
    layout = BASE.replace("initial_state: {inventory: 0, observed: -1, token: hidden}",
                          "initial_state: {token: hidden, observed: -1, inventory: 0}")
    assert compare_definitions(parse_yaml(BASE), parse_yaml(layout)).changes == ()
    assert parse_yaml(BASE).actors[0].address == "scenario:/actor/customer_a"


def test_t23_t28_actor_impact_is_conservative_and_cross_actor() -> None:
    changed = BASE.replace("{$literal: 1}", "{$literal: 2}")
    analysis = analyze_impact(parse_yaml(BASE), parse_yaml(changed))
    assert analysis.schema == "scenario.impact/2"
    direct = [item for item in analysis.records if item.classification is ImpactClassification.DIRECT]
    assert direct and direct[0].source_change.semantic_path.startswith("scenario:/actor/customer_a/")
    cross = [item for item in analysis.records if item.classification is ImpactClassification.POTENTIAL_CROSS_ACTOR]
    assert any(item.affected_semantic_path.startswith("scenario:/actor/customer_b/") for item in cross)
    payload = analysis.to_jsonable()
    assert payload["claims"]["complete_impact_proof"] is False
    assert "UNKNOWN_OR_UNSUPPORTED" in payload["summary"]["counts"]
    assert analysis.to_json_bytes() == analyze_impact(parse_yaml(BASE), parse_yaml(changed)).to_json_bytes()


def test_t29_t36_cross_major_integrity_duplicate_redaction_and_bounds(monkeypatch) -> None:
    _, result, schedule = produced()
    dsl1 = """dsl_version: 1
scenario: analysis
clock: {start: '2026-01-01T00:00:00Z'}
initial_state: {}
steps:
  - id: done
    transition: null
"""
    with pytest.raises(ValueError, match="cross-DSL-major"):
        compare_definitions(parse_yaml(BASE), parse_yaml(dsl1))
    encoded = canonical_result2_bytes(result)
    with pytest.raises(Engine2EvidenceError, match="duplicate"):
        read_result2(encoded.replace(b'{"actors":', b'{"actors":[],"actors":', 1))
    tampered = encoded.replace(result.result_hash.encode(), b"0" * 64)
    with pytest.raises(Engine2EvidenceError):
        read_result2(tampered)
    assert b"hidden" not in canonical_inspection_bytes(inspect(result))
    import scenario_engine.inspection.models as models
    monkeypatch.setattr(models, "MAX_INSPECTION_RECORDS", 1)
    with pytest.raises(Exception, match="traversal exceeds"):
        inspect(result)
    assert canonical_schedule_bytes(schedule)


def test_t47_t50_cross_process_cli_and_python_consumers(tmp_path: Path) -> None:
    source = tmp_path / "scenario.yaml"; source.write_text(BASE, encoding="utf-8")
    schedule = tmp_path / "schedule.json"; result = tmp_path / "result.json"
    run = invoke("--json", "run", str(source), "--seed", "generation", "--schedule-seed", "7",
                 "--schedule-out", str(schedule), "--result-out", str(result))
    assert run.returncode == 0
    inspected = invoke("--json", "inspect", str(result), "--kind", "result")
    explained = invoke("--json", "explain", str(result), "--schedule", str(schedule),
                       "--actor", "scenario:/actor/customer_a")
    assert inspected.returncode == explained.returncode == 0
    assert json.loads(inspected.stdout)["schema_version"] == "inspection.document/2"
    assert json.loads(explained.stdout)["schema_version"] == "inspection.explanation/2"
    code = f'''from scenario_engine.engine2 import read_result2\nfrom scenario_engine.inspection import inspect,canonical_inspection_bytes\nr=read_result2(open({str(result)!r},"rb").read());print(canonical_inspection_bytes(inspect(r)).hex())'''
    outputs = []
    for seed in ("1", "999"):
        env = os.environ.copy(); env.update({"PYTHONHASHSEED": seed, "PYTHONPATH": str(ROOT / "src")})
        outputs.append(subprocess.check_output([sys.executable, "-c", code], cwd=ROOT, env=env))
    assert outputs[0] == outputs[1]


def test_fixed_actor_analysis_golden() -> None:
    _, result, schedule = produced()
    import hashlib
    assert hashlib.sha256(canonical_inspection_bytes(inspect(result))).hexdigest() == "f5cff73b2f3d67fcc42aab19765673faeb52607af6876c8d9f1bd19029baebca"
    assert hashlib.sha256(canonical_explanation_bytes(explain_result(result, schedule=schedule))).hexdigest() == "32f19fff841bb889ed43b8b6fcbbcf435a85bf382b818ba8adcdecfd9e67db9b"
