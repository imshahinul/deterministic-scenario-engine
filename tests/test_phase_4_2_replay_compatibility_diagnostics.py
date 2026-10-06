from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from scenario_engine.cli import CLIExitCode


PYTHON = sys.executable
ROOT = Path(__file__).parents[1]
SCENARIO = """dsl_version: 1
scenario: diagnostic_case
clock: {start: '2026-01-01T00:00:00Z'}
resources:
  selected: {$input: selected}
initial_state: {selected: 0}
steps:
  - id: set
    write: {selected: {$resource: selected}}
    transition: null
"""


def invoke(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [PYTHON, "-m", "scenario_engine.cli", *args], cwd=ROOT,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        env={"PYTHONPATH": str(ROOT / "src")},
    )


@pytest.fixture
def replay_files(tmp_path: Path) -> tuple[Path, Path, Path]:
    scenario = tmp_path / "scenario.yaml"
    wrong = tmp_path / "wrong.yaml"
    artifact = tmp_path / "run.replay.json"
    scenario.write_text(SCENARIO, encoding="utf-8")
    wrong.write_text(SCENARIO.replace("diagnostic_case", "wrong_case"), encoding="utf-8")
    result = invoke(
        "run", str(scenario), "--seed", "seed", "--inputs", '{"selected":1}',
        "--replay-out", str(artifact),
    )
    assert result.returncode == CLIExitCode.SUCCESS
    return scenario, wrong, artifact


def assert_diagnostic(result: subprocess.CompletedProcess[bytes], code: bytes) -> None:
    assert result.returncode == CLIExitCode.REPLAY_COMPATIBILITY
    assert result.stdout == b""
    assert result.stderr.startswith(b"scenario: error: code=" + code + b"; category=REPLAY_COMPATIBILITY;")
    assert b"migration=MIGRATION_UNAVAILABLE" in result.stderr
    assert b"next_action=" in result.stderr
    assert b"Traceback" not in result.stderr


def test_wrong_scenario_reports_stable_identity_context(replay_files: tuple[Path, Path, Path]) -> None:
    _, wrong, artifact = replay_files
    result = invoke("replay", str(artifact), "--scenario", str(wrong), "--inputs", '{"selected":1}')
    assert_diagnostic(result, b"SCENARIO_MISMATCH")
    assert b"artifact_contract=suite.run/1" in result.stderr
    assert b"scenario_expected=diagnostic_case" in result.stderr
    assert b"scenario_received=wrong_case" in result.stderr
    assert b"next_action=SUPPLY_EXACT_SCENARIO" in result.stderr


def test_unsupported_engine_reports_versions_and_safe_action(replay_files: tuple[Path, Path, Path], tmp_path: Path) -> None:
    scenario, _, artifact = replay_files
    raw = json.loads(artifact.read_bytes())
    raw["compatibility"]["execution_contract"] = "scenario-engine/9.0.0"
    unsupported = tmp_path / "engine.json"
    unsupported.write_text(json.dumps(raw, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    result = invoke("replay", str(unsupported), "--scenario", str(scenario), "--inputs", '{"selected":1}')
    assert_diagnostic(result, b"ENGINE_VERSION_UNSUPPORTED")
    assert b"expected=scenario-engine/1.0.0" in result.stderr
    assert b"received=scenario-engine/9.0.0" in result.stderr
    assert b"next_action=USE_SUPPORTED_ENGINE" in result.stderr


def test_unsupported_manifest_reports_contract_and_no_known_migration(replay_files: tuple[Path, Path, Path], tmp_path: Path) -> None:
    scenario, _, artifact = replay_files
    raw = json.loads(artifact.read_bytes())
    raw["schema_version"] = "suite.run/2"
    unsupported = tmp_path / "manifest.json"
    unsupported.write_text(json.dumps(raw, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    first = invoke("--json", "replay", str(unsupported), "--scenario", str(scenario), "--inputs", '{"selected":1}')
    second = invoke("--json", "replay", str(unsupported), "--scenario", str(scenario), "--inputs", '{"selected":1}')
    assert first.stderr == second.stderr
    assert_diagnostic(first, b"MANIFEST_VERSION_UNSUPPORTED")
    assert b"artifact_contract=suite.run/2" in first.stderr
    assert b"expected=suite.run/1" in first.stderr
    assert b"received=suite.run/2" in first.stderr
    assert b"next_action=USE_SUPPORTED_MANIFEST_OR_MIGRATION" in first.stderr


def test_incomplete_supported_envelope_reports_replay_data_incomplete(replay_files: tuple[Path, Path, Path], tmp_path: Path) -> None:
    scenario, _, artifact = replay_files
    raw = json.loads(artifact.read_bytes())
    del raw["child_manifest"]
    incomplete = tmp_path / "incomplete.json"
    incomplete.write_text(json.dumps(raw, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    result = invoke("replay", str(incomplete), "--scenario", str(scenario), "--inputs", '{"selected":1}')
    assert_diagnostic(result, b"REPLAY_DATA_INCOMPLETE")
    assert b"artifact_contract=suite.run/1" in result.stderr
    assert b"next_action=SUPPLY_COMPLETE_REPLAY_DATA" in result.stderr


def test_replay_help_exposes_reason_code_failure_contract() -> None:
    result = invoke("replay", "--help")
    assert result.returncode == CLIExitCode.SUCCESS
    assert b"Incompatibility exits 5" in result.stdout
    assert b"stable replay reason code" in result.stdout
