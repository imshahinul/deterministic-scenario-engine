from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from scenario_engine.cli import CLIExitCode


ROOT = Path(__file__).parents[1]
BASE = """dsl_version: 1
scenario: machine_diagnostic
clock: {start: '2026-01-01T00:00:00Z'}
initial_state: {}
steps:
  - id: checkout
    transition: null
"""


def invoke(source: str, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, "-m", "scenario_engine.cli", *arguments, "-"],
        cwd=ROOT, input=source.encode(), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        check=False, env={"PYTHONPATH": str(ROOT / "src")},
    )


def envelope(result: subprocess.CompletedProcess[bytes], exit_code: int) -> dict[str, object]:
    assert result.returncode == exit_code
    assert result.stdout == b""
    value = json.loads(result.stderr)
    assert value["schema"] == "scenario.error/1"
    assert value["exit_code"] == exit_code
    assert isinstance(value["message"], str)
    assert b"Traceback" not in result.stderr
    return value


def test_schema_and_parse_errors_have_stable_bounded_envelopes() -> None:
    schema = invoke(BASE.replace("steps:\n  - id: checkout\n    transition: null", "steps: wrong"), "--json", "validate")
    value = envelope(schema, CLIExitCode.VALIDATION)
    assert value["code"] == "DSL_SCHEMA_ERROR"
    assert value["category"] == "DSL_SCHEMA"
    assert value["expected"] == "non-empty array"
    assert value["received"] == "string"

    malformed = envelope(invoke("not: [valid", "--json", "validate"), CLIExitCode.VALIDATION)
    assert malformed["code"] == "DSL_PARSE_ERROR"
    assert malformed["category"] == "DSL_SCHEMA"


def test_semantic_path_and_secret_redaction_are_preserved() -> None:
    secret = "secret-token-value"
    result = invoke(BASE.replace("transition: null", f"transition: {secret}"), "--json", "validate")
    value = envelope(result, CLIExitCode.VALIDATION)
    assert value["code"] == "DSL_SEMANTIC_ERROR"
    assert value["category"] == "DSL_SEMANTIC"
    assert value["semantic_path"] == "scenario:/step/checkout"
    assert "$.steps" not in result.stderr.decode()
    assert secret not in result.stderr.decode()


def test_same_error_is_byte_identical_and_optional_fields_are_omitted() -> None:
    first = invoke("not: [valid", "--json", "validate")
    second = invoke("not: [valid", "--json", "validate")
    assert first.stderr == second.stderr
    value = envelope(first, CLIExitCode.VALIDATION)
    assert "semantic_path" not in value
    assert "details" not in value


def test_path_error_uses_existing_error_channel_code_and_bounded_details(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "scenario_engine.cli", "--json", "verify", "relative"],
        cwd=tmp_path, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        env={"PYTHONPATH": str(ROOT / "src")},
    )
    value = envelope(result, CLIExitCode.SECURITY_OR_BOUND)
    assert value["code"] == "PATH_NOT_ABSOLUTE"
    assert value["category"] == "FILESYSTEM_TRUST_BOUNDARY"
    assert value["details"] == {"operation": "verify", "path_kind": "local_filesystem"}
    assert "traceback" not in json.dumps(value["details"]).lower()


def test_default_human_and_valid_json_success_are_unchanged() -> None:
    invalid = invoke("not: [valid", "validate")
    assert invalid.stderr.startswith(b"scenario: error: DSL_PARSE_ERROR\ncategory: DSL_SCHEMA\n")
    valid = invoke(BASE, "--json", "validate")
    assert valid.returncode == CLIExitCode.SUCCESS and valid.stderr == b""
    assert json.loads(valid.stdout) == {
        "command": "validate", "identity": json.loads(valid.stdout)["identity"], "valid": True,
    }


def test_json_mode_uses_the_existing_global_flag() -> None:
    value = envelope(invoke("not: [valid", "--json", "validate"), CLIExitCode.VALIDATION)
    assert value["schema"] == "scenario.error/1"
