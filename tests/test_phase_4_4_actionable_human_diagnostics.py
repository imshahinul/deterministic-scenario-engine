from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest

from scenario_engine.cli import CLIExitCode
from scenario_engine.diagnostics import semantic_address


ROOT = Path(__file__).parents[1]
BASE = """dsl_version: 1
scenario: diagnostic_case
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


def assert_actionable(result: subprocess.CompletedProcess[bytes], code: bytes) -> None:
    assert result.returncode == CLIExitCode.VALIDATION
    assert result.stdout == b""
    assert result.stderr.startswith(b"scenario: error: " + code + b"\ncategory: ")
    assert b"\nmessage:\n" in result.stderr
    assert b"\nexpected:\n" in result.stderr
    assert b"\nreceived:\n" in result.stderr
    assert b"\nnext action:\n" in result.stderr
    assert b"Traceback" not in result.stderr


def test_malformed_yaml_is_actionable_traceback_free_and_deterministic() -> None:
    first = invoke("not: [valid", "validate")
    second = invoke("not: [valid", "validate")
    assert_actionable(first, b"DSL_PARSE_ERROR")
    assert first.stderr == second.stderr
    assert b"valid DSL 1 YAML" in first.stderr
    assert b"malformed YAML" in first.stderr


def test_missing_required_field_has_bounded_expected_received() -> None:
    result = invoke(BASE.replace("initial_state: {}\n", ""), "validate")
    assert_actionable(result, b"DSL_SCHEMA_ERROR")
    assert b"required field(s): initial_state" in result.stderr
    assert b"\nmissing\n" in result.stderr


@pytest.mark.parametrize(
    ("source", "expected", "received"),
    (
        (BASE.replace("steps:\n  - id: checkout\n    transition: null", "steps: wrong"), b"non-empty array", b"string"),
        (BASE.replace("transition: null", "transition: {}"), b"non-empty string", b"object"),
    ),
)
def test_invalid_type_or_value_reports_safe_shape(source: str, expected: bytes, received: bytes) -> None:
    result = invoke(source, "validate")
    assert_actionable(result, b"DSL_SCHEMA_ERROR")
    assert expected in result.stderr and received in result.stderr


def test_semantic_failure_uses_semantic_address_and_redacts_received_value() -> None:
    secret = "secret-token-value"
    source = BASE.replace("transition: null", f"transition: {secret}")
    result = invoke(source, "validate")
    assert_actionable(result, b"DSL_SEMANTIC_ERROR")
    assert b"path:\nscenario:/step/checkout\n" in result.stderr
    assert b"$.steps" not in result.stderr
    assert secret.encode() not in result.stderr


def test_valid_scenario_and_validate_help_are_unchanged_success_surfaces() -> None:
    result = invoke(BASE, "validate")
    assert result.returncode == CLIExitCode.SUCCESS
    assert result.stderr == b"" and result.stdout.startswith(b"valid scenario ")
    help_result = subprocess.run(
        [sys.executable, "-m", "scenario_engine.cli", "validate", "--help"], cwd=ROOT,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        env={"PYTHONPATH": str(ROOT / "src")},
    )
    assert b"stable diagnostic code" in help_result.stdout
    assert b"scenario.semantic-address/1" in help_result.stdout


def test_semantic_address_is_canonical_and_not_a_yaml_path() -> None:
    address = semantic_address(("step", "check out/one"))
    assert address == "scenario:/step/check%20out%2Fone"
    assert not address.startswith("$.")
