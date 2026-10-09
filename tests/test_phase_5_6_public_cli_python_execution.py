from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

from scenario_engine.compatibility import CompatibilityClassification, classify_engine_contract
from scenario_engine.engine2 import (
    Engine2Result, canonical_result2_bytes, execute_engine2, replay_engine2,
    validate_engine2,
)
from scenario_engine.schedule import canonical_schedule_bytes


ROOT = Path(__file__).parents[1]
SCENARIO = """dsl_version: 2
scenario: public-actors
clock: {start: '2026-01-01T00:00:00Z'}
initial_state: {value: 0, observed: -1}
actors:
  - id: reader
    steps:
      - id: read
        write: {observed: {$state: value}}
        transition: null
  - id: writer
    steps:
      - id: write
        write: {value: {$add: [{$state: value}, {$literal: 1}]}}
        advance: {seconds: 1}
        transition: null
"""


def invoke(*arguments: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, "-m", "scenario_engine.cli", *arguments], cwd=ROOT,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        env={"PYTHONPATH": str(ROOT / "src")},
    )


def test_public_python_execute_replay_and_compatibility() -> None:
    scenario = validate_engine2(SCENARIO)
    result, schedule = execute_engine2(scenario, "generation", 7, run_index=3)
    assert isinstance(result, Engine2Result)
    assert result.contract == "scenario.result/2"
    assert schedule.contract == "scenario.schedule/1"
    assert replay_engine2(
        canonical_result2_bytes(result), canonical_schedule_bytes(schedule), scenario,
    ) == result
    decision = classify_engine_contract(
        dsl_version=2, engine_version="2.0.0", result_contract="scenario.result/2",
        operation="replay",
    )
    assert decision.classification is CompatibilityClassification.SUPPORTED_EXACT


def test_cli_execute_exact_replay_and_repeat_bytes(tmp_path: Path) -> None:
    source = tmp_path / "scenario.yaml"
    source.write_text(SCENARIO, encoding="utf-8")
    schedule_one, schedule_two = tmp_path / "schedule-1.json", tmp_path / "schedule-2.json"
    result_one, result_two = tmp_path / "result-1.json", tmp_path / "result-2.json"
    common = (str(source), "--seed", "generation", "--schedule-seed", "7", "--run-index", "3")
    first = invoke("--json", "run", *common, "--schedule-out", str(schedule_one), "--result-out", str(result_one))
    second = invoke("--json", "run", *common, "--schedule-out", str(schedule_two), "--result-out", str(result_two))
    assert first.returncode == second.returncode == 0
    assert first.stdout.rstrip(b"\n") == result_one.read_bytes() == result_two.read_bytes()
    assert schedule_one.read_bytes() == schedule_two.read_bytes()
    result = json.loads(result_one.read_bytes()); schedule = json.loads(schedule_one.read_bytes())
    assert result["schedule_reference"]["schedule_hash"] == schedule["schedule_hash"]
    identity = {key: value for key, value in schedule.items() if key != "schedule_hash"}
    assert hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode()).hexdigest() == schedule["schedule_hash"]
    replay = invoke("--json", "replay", str(result_one), "--scenario", str(source), "--schedule", str(schedule_one))
    assert replay.returncode == 0 and replay.stdout.rstrip(b"\n") == result_one.read_bytes()


def test_missing_coordinates_tampering_remote_and_output_rollback(tmp_path: Path) -> None:
    source = tmp_path / "scenario.yaml"; source.write_text(SCENARIO, encoding="utf-8")
    missing_seed = invoke("--json", "run", str(source), "--seed", "generation", "--schedule-out", str(tmp_path / "s.json"))
    assert missing_seed.returncode == 2 and json.loads(missing_seed.stderr)["code"] == "SCHEDULE_SEED_REQUIRED"
    schedule = tmp_path / "schedule.json"; result = tmp_path / "result.json"
    assert invoke("--json", "run", str(source), "--seed", "generation", "--schedule-seed", "7",
                  "--schedule-out", str(schedule), "--result-out", str(result)).returncode == 0
    no_evidence = invoke("--json", "replay", str(result), "--scenario", str(source))
    assert no_evidence.returncode == 5 and json.loads(no_evidence.stderr)["code"] == "SCHEDULE_EVIDENCE_REQUIRED"
    raw = json.loads(schedule.read_bytes()); raw["records"][0]["selected_actor"] = "scenario:/actor/writer"
    corrupted = tmp_path / "corrupted.json"
    corrupted.write_text(json.dumps(raw, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    rejected = invoke("--json", "replay", str(result), "--scenario", str(source), "--schedule", str(corrupted))
    assert rejected.returncode in (3, 5) and b"Traceback" not in rejected.stderr
    remote = invoke("--json", "run", str(source), "--seed", "generation", "--schedule-seed", "7",
                    "--schedule-out", "https://example.invalid/schedule.json")
    assert remote.returncode == 6 and json.loads(remote.stderr)["code"] == "PATH_REMOTE_FORBIDDEN"
    first = tmp_path / "must-rollback.json"; existing = tmp_path / "existing.json"; existing.write_bytes(b"occupied")
    failed = invoke("--json", "run", str(source), "--seed", "generation", "--schedule-seed", "7",
                    "--schedule-out", str(first), "--result-out", str(existing))
    assert failed.returncode == 7 and not first.exists() and existing.read_bytes() == b"occupied"


def test_invalid_secret_like_schedule_seed_is_redacted(tmp_path: Path) -> None:
    source = tmp_path / "scenario.yaml"; source.write_text(SCENARIO, encoding="utf-8")
    secret = "super-secret-token"
    rejected = invoke("--json", "run", str(source), "--seed", "generation", "--schedule-seed", secret,
                      "--schedule-out", str(tmp_path / "schedule.json"))
    assert rejected.returncode == 2 and secret.encode() not in rejected.stderr
    assert json.loads(rejected.stderr)["code"] == "SCHEDULE_SEED_INVALID"


def test_engine2_inspection_dispatches_to_actor_aware_contract(tmp_path: Path) -> None:
    source = tmp_path / "scenario.yaml"; source.write_text(SCENARIO, encoding="utf-8")
    schedule = tmp_path / "schedule.json"; result = tmp_path / "result.json"
    assert invoke("--json", "run", str(source), "--seed", "generation", "--schedule-seed", "7",
                  "--schedule-out", str(schedule), "--result-out", str(result)).returncode == 0
    inspected = invoke("--json", "inspect", str(result), "--kind", "result")
    payload = json.loads(inspected.stdout)
    assert inspected.returncode == 0 and inspected.stderr == b""
    assert payload["schema_version"] == "inspection.document/2"
    assert payload["target_kind"] == "engine2_result"
