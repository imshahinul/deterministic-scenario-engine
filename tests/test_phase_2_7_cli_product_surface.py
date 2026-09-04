from __future__ import annotations

import ast
import importlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from scenario_engine.cli import CLIExitCode
from scenario_engine.cli.main import MAX_AUXILIARY_JSON_BYTES, MAX_CLI_INPUT_BYTES
from scenario_engine.dsl import compile_document, parse_yaml, run_scenario
from scenario_engine.inspection import (
    canonical_explanation_bytes, canonical_inspection_bytes, explain_result, inspect_result,
)
from scenario_engine.suite import (
    CompatibilityRecord, ExecutionContext, ExecutionReplaySupport, RunManifestEnvelope,
    canonical_suite_bytes, read_v1_result_bytes,
)


PYTHON = sys.executable
ROOT = Path(__file__).parents[1]


SCENARIO = """dsl_version: 1
scenario: cli_case
clock: {start: '2026-01-01T00:00:00Z'}
resources:
  selected: {$input: selected}
initial_state: {value: 0, random: 0}
steps:
  - id: apply
    generate: {draw: {$int: [1, 1000]}}
    write:
      value: {$resource: selected}
      random: {$local: draw}
    transition: null
"""


def invoke(*args: str, stdin: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [PYTHON, "-m", "scenario_engine.cli", *args], cwd=ROOT, input=stdin,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        env={"PYTHONPATH": str(ROOT / "src")},
    )


@pytest.fixture
def scenario_file(tmp_path: Path) -> Path:
    path = tmp_path / "scenario.yaml"
    path.write_text(SCENARIO, encoding="utf-8")
    return path


def direct_result(seed: str = "seed", run_index: int = 0, selected: int = 1):
    target = compile_document(parse_yaml(SCENARIO))
    return run_scenario(target, seed, run_index=run_index, inputs={"selected": selected})


def test_help_lists_exact_frozen_command_family_and_unknown_is_stable() -> None:
    result = invoke("--help")
    assert result.returncode == 0 and result.stderr == b""
    for command in ("validate", "run", "replay", "hash", "inspect", "explain", "diff", "matrix", "batch"):
        assert command.encode() in result.stdout
    unknown = invoke("unknown")
    assert unknown.returncode == CLIExitCode.USAGE
    assert unknown.stdout == b""
    assert unknown.stderr == b"scenario: error: invalid command-line arguments\n"
    assert b"Traceback" not in unknown.stderr


def test_module_invocation_validate_and_no_execution(scenario_file: Path, monkeypatch, capsys) -> None:
    implementation = importlib.import_module("scenario_engine.cli.main")

    monkeypatch.setattr(implementation, "run_scenario", lambda *a, **k: pytest.fail("validation executed"))
    assert implementation.main(["--json", "validate", str(scenario_file)]) == CLIExitCode.SUCCESS
    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["command"] == "validate" and payload["valid"] is True
    assert payload["identity"] == direct_result().manifest.scenario_canonical_hash
    invalid = invoke("validate", "-", stdin=b"not: [valid")
    assert invalid.returncode == CLIExitCode.VALIDATION
    assert invalid.stdout == b"" and b"DSLParseError" in invalid.stderr


def test_run_is_byte_stable_and_equals_direct_library(scenario_file: Path) -> None:
    args = ("--json", "run", str(scenario_file), "--seed", "seed", "--run-index", "7", "--inputs", '{"selected":9}')
    first, second = invoke(*args), invoke(*args)
    assert first.returncode == second.returncode == 0
    assert first.stderr == second.stderr == b""
    assert first.stdout == second.stdout == direct_result("seed", 7, 9).to_json_bytes() + b"\n"


def test_replay_supported_equals_library_and_v1_contract_is_rejected(scenario_file: Path, tmp_path: Path) -> None:
    expected = direct_result("seed", 3, 4)
    manifest = expected.manifest
    envelope = RunManifestEnvelope(
        root_scenario_identity=expected.scenario_id,
        execution_context=ExecutionContext(
            manifest.root_seed, manifest.run_index, manifest.locale, manifest.reference_clock_start,
        ),
        compatibility=CompatibilityRecord(
            "scenario-engine/1.0.0", ExecutionReplaySupport.SUPPORTED,
        ),
        child_manifest=manifest,
    )
    supported = tmp_path / "run-manifest.json"
    supported.write_bytes(canonical_suite_bytes(envelope))
    replay = invoke("--json", "replay", str(supported), "--scenario", str(scenario_file), "--inputs", '{"selected":4}')
    assert replay.returncode == 0
    assert replay.stdout == expected.to_json_bytes() + b"\n"

    v1 = tmp_path / "v1-manifest.json"
    v1.write_text(json.dumps(manifest.normalized(), sort_keys=True, separators=(",", ":")), encoding="utf-8")
    rejected = invoke("replay", str(v1), "--scenario", str(scenario_file), "--inputs", '{"selected":4}')
    assert rejected.returncode == CLIExitCode.REPLAY_COMPATIBILITY
    assert rejected.stdout == b""
    assert rejected.stderr == b"scenario: error: execution replay is not supported for the recorded contract\n"


def test_hash_is_semantic_and_formatting_independent(scenario_file: Path, tmp_path: Path) -> None:
    reformatted = tmp_path / "formatted.yaml"
    reformatted.write_text("\n# comment\n" + SCENARIO.replace("scenario: cli_case", "scenario: cli_case  # same"), encoding="utf-8")
    first = invoke("--json", "hash", str(scenario_file))
    second = invoke("--json", "hash", str(reformatted))
    assert first.returncode == second.returncode == 0
    assert first.stdout == second.stdout
    assert json.loads(first.stdout)["hash"] == direct_result().manifest.scenario_canonical_hash


def test_composition_hash_is_checkout_path_independent(tmp_path: Path) -> None:
    def checkout(root: Path) -> Path:
        (root / "mods").mkdir(parents=True)
        (root / "mods/input.yaml").write_text(
            "dsl_version: 1\nmodule: input\nresources:\n  selected: {input: selected, required: false, default: 1}\n",
            encoding="utf-8",
        )
        source = root / "root.yaml"
        source.write_text("""dsl_version: 1
scenario: composed_cli
clock: {start: '2026-01-01T00:00:00Z'}
composition: {modules: {input: mods/input.yaml}}
initial_state: {value: 0}
steps:
  - id: apply
    write: {value: {$resource: input.selected}}
    transition: null
""", encoding="utf-8")
        return source
    left, right = checkout(tmp_path / "a"), checkout(tmp_path / "b")
    a = invoke("--json", "hash", str(left), "--root", str(left.parent.resolve()))
    b = invoke("--json", "hash", str(right), "--root", str(right.parent.resolve()))
    assert a.returncode == b.returncode == 0 and a.stdout == b.stdout
    assert str(tmp_path).encode() not in a.stdout


def test_inspect_and_explain_equal_phase_2_5_without_rerun(tmp_path: Path) -> None:
    result = direct_result()
    path = tmp_path / "result.json"
    path.write_bytes(result.to_json_bytes())
    read = read_v1_result_bytes(result.to_json_bytes())
    inspected = invoke("--json", "inspect", str(path))
    explained = invoke("--json", "explain", str(path))
    assert inspected.stdout == canonical_inspection_bytes(inspect_result(read)) + b"\n"
    assert explained.stdout == canonical_explanation_bytes(explain_result(read)) + b"\n"
    assert b"not_unambiguously_recorded" in explained.stdout


def test_diff_equal_different_first_complete_and_clean_streams(tmp_path: Path) -> None:
    left, right = direct_result(selected=1), direct_result(selected=2)
    left_path, right_path = tmp_path / "left.json", tmp_path / "right.json"
    left_path.write_bytes(left.to_json_bytes())
    right_path.write_bytes(right.to_json_bytes())
    equal = invoke("--json", "diff", str(left_path), str(left_path), "--mode", "complete")
    assert equal.returncode == 0 and json.loads(equal.stdout)["equal"] is True and equal.stderr == b""
    first = invoke("--json", "diff", str(left_path), str(right_path), "--mode", "first")
    complete = invoke("--json", "diff", str(left_path), str(right_path), "--mode", "complete")
    assert first.returncode == complete.returncode == CLIExitCode.DIFFERENT
    first_value, complete_value = json.loads(first.stdout), json.loads(complete.stdout)
    assert len(first_value["records"]) == 1
    assert len(complete_value["records"]) > 1
    assert all(record["path"].startswith("/") for record in complete_value["records"])
    assert first.stderr == complete.stderr == b""


def test_matrix_describe_order_identity_and_single_case_equivalence(scenario_file: Path) -> None:
    dimensions = '[{"name":"selected","values":[3,4,5]}]'
    described = invoke("--json", "matrix", str(scenario_file), "--seed", "seed", "--dimensions", dimensions, "--describe")
    assert described.returncode == 0
    value = json.loads(described.stdout)
    assert [case["original_index"] for case in value["cases"]] == [0, 1, 2]
    assert [case["assignment"]["selected"] for case in value["cases"]] == [3, 4, 5]
    case = value["cases"][1]
    selected = invoke("--json", "matrix", str(scenario_file), "--seed", "seed", "--dimensions", dimensions, "--case", case["case_id"])
    assert selected.returncode == 0
    assert selected.stdout == direct_result("seed", case["original_index"], 4).to_json_bytes() + b"\n"


def test_batch_preserves_plan_order_statuses_and_deterministic_json(scenario_file: Path, tmp_path: Path) -> None:
    plan = tmp_path / "batch.json"
    plan.write_text(json.dumps({"runs": [
        {"id": "second", "scenario": scenario_file.name, "seed": "seed", "run_index": 2, "inputs": {"selected": 2}},
        {"id": "first", "scenario": scenario_file.name, "seed": "seed", "run_index": 1, "inputs": {"selected": 1}},
    ]}), encoding="utf-8")
    first = invoke("--json", "batch", str(plan), "--workers", "1")
    second = invoke("--json", "batch", str(plan), "--workers", "2", "--max-in-flight", "2")
    assert first.returncode == second.returncode == 0
    assert first.stdout == second.stdout and first.stderr == second.stderr == b""
    document = json.loads(first.stdout)
    items = next(section for section in document["sections"] if section["name"] == "items")
    assert [item["run_id"] for item in items["evidence"]["value"]] == ["second", "first"]
    assert [item["status"] for item in items["evidence"]["value"]] == ["success", "success"]


def test_security_bounds_network_and_no_secret_or_traceback(tmp_path: Path) -> None:
    remote = invoke("validate", "https://example.invalid/scenario.yaml")
    assert remote.returncode == CLIExitCode.SECURITY_OR_BOUND
    assert b"example.invalid" not in remote.stderr and b"Traceback" not in remote.stderr
    oversized = tmp_path / "oversized.yaml"
    oversized.write_bytes(b" " * (MAX_CLI_INPUT_BYTES + 1))
    bounded = invoke("validate", str(oversized))
    assert bounded.returncode == CLIExitCode.SECURITY_OR_BOUND
    assert str(tmp_path).encode() not in bounded.stderr
    secret = "secret-token-value"
    bad = invoke("run", "-", "--seed", "seed", "--inputs", json.dumps({"token": secret}), stdin=b"bad: [")
    assert secret.encode() not in bad.stderr and b"Traceback" not in bad.stderr
    assert MAX_AUXILIARY_JSON_BYTES == 1_048_576


def test_cli_static_purity_version_and_console_script_contract() -> None:
    forbidden = {"random", "secrets", "socket", "subprocess", "multiprocessing", "importlib", "os", "time", "urllib", "requests"}
    for path in (ROOT / "src/scenario_engine/cli").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
            assert not isinstance(node, (ast.Global, ast.Nonlocal))
        assert imported.isdisjoint(forbidden)
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'scenario = "scenario_engine.cli:main"' in pyproject
    assert 'VERSION = "1.0.0"' in (ROOT / "src/scenario_engine/_version.py").read_text(encoding="utf-8")
