from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from scenario_engine.definition_diff import compare_definitions
from scenario_engine.diagnostics import (
    HumanDiagnostic, MAX_DIAGNOSTIC_DETAILS, MAX_SEMANTIC_ADDRESS_DEPTH,
    error_envelope, render_error_envelope, render_human_diagnostic, semantic_address,
)
from scenario_engine.dsl import parse_yaml
from scenario_engine.impact import analyze_impact
from scenario_engine.scaffolding import (
    MAX_SCAFFOLD_OUTPUT_BYTES, ScaffoldProposal, ScaffoldProviderFailedError,
    ScaffoldRequest, ScaffoldRequestInvalidError, scaffold_scenario,
)


ROOT = Path(__file__).parents[1]
BASE = """dsl_version: 1
scenario: hardening
clock: {start: '2026-01-01T00:00:00Z'}
initial_state: {value: 0}
steps:
  - id: finish
    write: {value: {$literal: 1}}
    transition: null
"""


def invoke(*arguments: str, stdin: bytes = b"") -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, "-m", "scenario_engine.cli", *arguments], cwd=ROOT,
        input=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        env={"PYTHONPATH": str(ROOT / "src")}, timeout=20,
    )


def test_semantic_address_enforces_canonical_namespace_depth_and_length() -> None:
    composed = "e\u0301 /%\n"
    assert semantic_address(("step", composed)) == "scenario:/step/%C3%A9%20%2F%25%0A"
    assert semantic_address(("unknown", "id")) is None
    assert semantic_address(("actor", "reserved")) is None
    assert semantic_address(("lane", "reserved")) is None
    assert semantic_address(("x-vendor", "opaque")) == "scenario:/x-vendor/opaque"
    assert semantic_address(*(("step", str(i)) for i in range(MAX_SEMANTIC_ADDRESS_DEPTH)))
    assert semantic_address(*(("step", str(i)) for i in range(MAX_SEMANTIC_ADDRESS_DEPTH + 1))) is None
    assert semantic_address(("step", "x" * 2048)) is None
    assert semantic_address(("step", "\ud800")) is None


def test_diagnostics_are_bounded_deterministic_control_safe_and_secret_redacted() -> None:
    secret = "do-not-disclose"
    diagnostic = HumanDiagnostic(
        "DSL_TEST\x00", "DSL_SCHEMA", "<script>\n" + "x" * 1000,
        expected="safe\nvalue", received="unicode: λ",
        details={"z": "last", "client_secret": secret, "api_key": secret,
                 **{f"item-{index:04d}": "v" for index in range(MAX_DIAGNOSTIC_DETAILS + 10)}},
    )
    first = render_error_envelope(diagnostic, 3)
    assert first == render_error_envelope(diagnostic, 3)
    assert secret not in first and "Traceback" not in first
    value = json.loads(first)
    assert len(value["details"]) == MAX_DIAGNOSTIC_DETAILS
    assert value["details"]["api_key"] == "[REDACTED]"
    human = render_human_diagnostic(diagnostic)
    assert "\x00" not in human and "\n<script> x" in human


@pytest.mark.parametrize("payload", (b"", b"not: [yaml", b"\xff", b"[]", b"{}"))
@pytest.mark.parametrize("command", ("validate", "run"))
def test_malformed_dsl_commands_are_bounded_without_traceback(command: str, payload: bytes) -> None:
    arguments = ["--json", command]
    if command == "run":
        arguments.extend(("--seed", "hardening"))
    arguments.append("-")
    result = invoke(*arguments, stdin=payload)
    assert result.returncode in {3, 4}
    assert result.stdout == b"" and b"Traceback" not in result.stderr
    assert json.loads(result.stderr)["schema"] == "scenario.error/1"


class _HugeProvider:
    provider_id = "huge"
    provider_version = "1"

    def propose(self, request: ScaffoldRequest) -> ScaffoldProposal:
        return ScaffoldProposal("x" * (MAX_SCAFFOLD_OUTPUT_BYTES + 1), self.provider_id, self.provider_version)


class _MalformedProvider:
    provider_id = "malformed"
    provider_version = "1"

    def propose(self, request: ScaffoldRequest) -> object:
        return object()


def test_scaffold_rejects_oversized_intent_and_unbounded_or_malformed_provider_results() -> None:
    with pytest.raises(ScaffoldRequestInvalidError):
        ScaffoldRequest("draft", ("finish",), "2" * 129)
    request = ScaffoldRequest("draft", ("finish",))
    with pytest.raises(ScaffoldProviderFailedError):
        scaffold_scenario(request, provider="huge", providers={"huge": _HugeProvider()})
    with pytest.raises(ScaffoldProviderFailedError):
        scaffold_scenario(request, provider="malformed", providers={"malformed": _MalformedProvider()})


def test_definition_diff_and_zero_change_impact_are_byte_deterministic_and_layout_independent() -> None:
    left = parse_yaml(BASE)
    right = parse_yaml("\n# layout only\n" + BASE.replace("initial_state: {value: 0}", "initial_state:\n  value: 0"))
    differences = [compare_definitions(left, right).to_json_bytes() for _ in range(3)]
    impacts = [analyze_impact(left, right).to_json_bytes() for _ in range(3)]
    assert len(set(differences)) == len(set(impacts)) == 1
    assert json.loads(differences[0])["changes"] == []
    impact = json.loads(impacts[0])
    assert impact["summary"]["impacted_entity_count"] == 0
    assert impact["claims"]["unknown_means_unaffected"] is False


def test_cli_malformed_artifacts_and_remote_trace_paths_fail_closed() -> None:
    for command in (("--json", "inspect", "-"), ("--json", "explain", "-"),
                    ("--json", "replay", "-", "--scenario", "missing.yaml")):
        result = invoke(*command, stdin=b'{"truncated":')
        assert result.returncode != 0 and b"Traceback" not in result.stderr
        assert json.loads(result.stderr)["schema"] == "scenario.error/1"
    remote = invoke("--json", "trace-view", "file:///tmp/input", "--out", "/tmp/output.html")
    assert remote.returncode == 6
    assert json.loads(remote.stderr)["code"] == "PATH_REMOTE_FORBIDDEN"

