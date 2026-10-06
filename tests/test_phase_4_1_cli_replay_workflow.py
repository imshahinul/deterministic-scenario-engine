from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from scenario_engine.cli import CLIExitCode
from scenario_engine.suite import RunManifestEnvelope, canonical_suite_bytes, parse_suite_bytes


PYTHON = sys.executable
ROOT = Path(__file__).parents[1]
SCENARIO = """dsl_version: 1
scenario: replay_case
clock: {start: '2026-01-01T00:00:00Z'}
resources:
  selected: {$input: selected}
initial_state: {selected: 0}
steps:
  - id: apply
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
def scenarios(tmp_path: Path) -> tuple[Path, Path]:
    expected = tmp_path / "expected.yaml"
    wrong = tmp_path / "wrong.yaml"
    expected.write_text(SCENARIO, encoding="utf-8")
    wrong.write_text(SCENARIO.replace("scenario: replay_case", "scenario: wrong_case"), encoding="utf-8")
    return expected, wrong


def test_run_emits_canonical_supported_replay_artifact_and_replay_is_deterministic(
    scenarios: tuple[Path, Path], tmp_path: Path,
) -> None:
    scenario, _ = scenarios
    first_artifact = tmp_path / "first.replay.json"
    second_artifact = tmp_path / "second.replay.json"
    run_args = ("--json", "run", str(scenario), "--seed", "seed", "--run-index", "3",
                "--inputs", '{"selected":7}')
    first = invoke(*run_args, "--replay-out", str(first_artifact))
    second = invoke(*run_args, "--replay-out", str(second_artifact))

    assert first.returncode == second.returncode == CLIExitCode.SUCCESS
    assert first.stdout == second.stdout and first.stderr == second.stderr == b""
    assert first_artifact.read_bytes() == second_artifact.read_bytes()
    envelope = parse_suite_bytes(first_artifact.read_bytes())
    assert isinstance(envelope, RunManifestEnvelope)
    assert envelope.schema_version == "suite.run/1"
    assert envelope.root_scenario_identity == "replay_case"
    assert envelope.compatibility.execution_contract == "scenario-engine/1.0.0"
    assert envelope.child_manifest is not None
    assert envelope.child_manifest.engine_version == "1.0.0"
    assert envelope.child_manifest.dsl_version == 1
    assert canonical_suite_bytes(envelope) == first_artifact.read_bytes()

    replay = invoke("--json", "replay", str(first_artifact), "--scenario", str(scenario),
                    "--inputs", '{"selected":7}')
    assert replay.returncode == CLIExitCode.SUCCESS
    assert replay.stderr == b""
    assert replay.stdout == first.stdout


def test_run_without_replay_output_is_unchanged_and_destination_is_absent_only(
    scenarios: tuple[Path, Path], tmp_path: Path,
) -> None:
    scenario, _ = scenarios
    ordinary = invoke("--json", "run", str(scenario), "--seed", "seed", "--inputs", '{"selected":7}')
    destination = tmp_path / "existing.json"
    destination.write_bytes(b"preserve")
    rejected = invoke("run", str(scenario), "--seed", "seed", "--inputs", '{"selected":7}',
                      "--replay-out", str(destination))
    assert ordinary.returncode == CLIExitCode.SUCCESS
    assert rejected.returncode == CLIExitCode.IO
    assert destination.read_bytes() == b"preserve"


def test_wrong_scenario_and_unsupported_engine_fail_closed(
    scenarios: tuple[Path, Path], tmp_path: Path,
) -> None:
    scenario, wrong = scenarios
    artifact = tmp_path / "run.replay.json"
    assert invoke("run", str(scenario), "--seed", "seed", "--inputs", '{"selected":7}',
                  "--replay-out", str(artifact)).returncode == 0
    mismatch = invoke("replay", str(artifact), "--scenario", str(wrong), "--inputs", '{"selected":7}')
    assert mismatch.returncode == CLIExitCode.REPLAY_COMPATIBILITY
    assert mismatch.stdout == b""

    raw = json.loads(artifact.read_bytes())
    raw["compatibility"]["execution_contract"] = "scenario-engine/9.0.0"
    unsupported = tmp_path / "unsupported.replay.json"
    unsupported.write_text(json.dumps(raw, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    result = invoke("replay", str(unsupported), "--scenario", str(scenario), "--inputs", '{"selected":7}')
    assert result.returncode == CLIExitCode.REPLAY_COMPATIBILITY
    assert result.stdout == b""


@pytest.mark.parametrize("payload", [b"{", b"{}", b'{"$model":"RunManifestEnvelope"}'])
def test_malformed_and_incomplete_replay_artifacts_fail_closed(
    scenarios: tuple[Path, Path], tmp_path: Path, payload: bytes,
) -> None:
    scenario, _ = scenarios
    artifact = tmp_path / "invalid.json"
    artifact.write_bytes(payload)
    result = invoke("replay", str(artifact), "--scenario", str(scenario), "--inputs", '{"selected":7}')
    expected = (CLIExitCode.REPLAY_COMPATIBILITY
                if payload == b'{"$model":"RunManifestEnvelope"}' else CLIExitCode.VALIDATION)
    assert result.returncode == expected
    assert result.stdout == b""
    assert b"Traceback" not in result.stderr


def test_unsupported_manifest_version_and_missing_artifact_fail_closed(
    scenarios: tuple[Path, Path], tmp_path: Path,
) -> None:
    scenario, _ = scenarios
    artifact = tmp_path / "run.replay.json"
    assert invoke("run", str(scenario), "--seed", "seed", "--inputs", '{"selected":7}',
                  "--replay-out", str(artifact)).returncode == 0
    raw = json.loads(artifact.read_bytes())
    raw["schema_version"] = "suite.run/2"
    unsupported = tmp_path / "unsupported-manifest.json"
    unsupported.write_text(json.dumps(raw, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    version = invoke("replay", str(unsupported), "--scenario", str(scenario), "--inputs", '{"selected":7}')
    missing = invoke("replay", str(tmp_path / "missing.json"), "--scenario", str(scenario))
    assert version.returncode == CLIExitCode.REPLAY_COMPATIBILITY
    assert missing.returncode == CLIExitCode.IO
    assert version.stdout == missing.stdout == b""


def test_help_exposes_public_run_to_replay_workflow() -> None:
    run_help = invoke("run", "--help")
    replay_help = invoke("replay", "--help")
    assert run_help.returncode == replay_help.returncode == 0
    assert b"--replay-out PATH" in run_help.stdout
    assert b"supported suite.run/1 replay artifact" in run_help.stdout
    assert b"supported suite.run/1 recorded manifest" in replay_help.stdout
