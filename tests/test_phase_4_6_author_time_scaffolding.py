from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from scenario_engine.cli import CLIExitCode
from scenario_engine.dsl import compile_document, parse_yaml, run_scenario
from scenario_engine.scaffolding import (
    ScaffoldOutputInvalidError, ScaffoldProposal, ScaffoldProviderFailedError,
    ScaffoldRequest, scaffold_scenario,
)


ROOT = Path(__file__).parents[1]


def invoke(*arguments: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, "-m", "scenario_engine.cli", *arguments], cwd=ROOT,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        env={"PYTHONPATH": str(ROOT / "src")},
    )


def test_offline_proposal_is_identical_and_passes_ordinary_validation() -> None:
    request = ScaffoldRequest("checkout_draft", ("create", "checkout"))
    first = scaffold_scenario(request)
    second = scaffold_scenario(request)
    assert first == second
    assert first.proposed_dsl.encode() == second.proposed_dsl.encode()
    compiled = compile_document(parse_yaml(first.proposed_dsl))
    assert compiled.document.dsl_version == 1
    assert first.provider == "deterministic-template"
    assert first.validated is True
    assert "provider" not in compiled.document.initial_state


def test_cli_stdout_is_draft_and_never_auto_executes(tmp_path: Path) -> None:
    result = invoke("scaffold", "draft", "--step", "finish")
    assert result.returncode == CLIExitCode.SUCCESS and result.stderr == b""
    assert result.stdout.startswith(b"dsl_version: 1\n")
    assert b'"manifest"' not in result.stdout and b'"history"' not in result.stdout
    draft = tmp_path / "draft.yaml"
    draft.write_bytes(result.stdout)
    validated = invoke("validate", str(draft))
    assert validated.returncode == CLIExitCode.SUCCESS
    explicit = invoke("--json", "run", str(draft), "--seed", "reviewed")
    assert explicit.returncode == CLIExitCode.SUCCESS
    assert json.loads(explicit.stdout)["state"]["scaffold_complete"] is True


@pytest.mark.parametrize(
    ("arguments", "code"),
    [
        (("--json", "scaffold", "bad/id", "--step", "finish"), "SCAFFOLD_REQUEST_INVALID"),
        (("--json", "scaffold", "draft", "--step", "finish", "--provider", "missing"),
         "SCAFFOLD_PROVIDER_NOT_FOUND"),
    ],
)
def test_cli_failures_use_stable_scenario_error_envelope(arguments: tuple[str, ...], code: str) -> None:
    result = invoke(*arguments)
    assert result.returncode == CLIExitCode.VALIDATION and result.stdout == b""
    value = json.loads(result.stderr)
    assert value["schema"] == "scenario.error/1"
    assert value["category"] == "SCAFFOLD_AUTHORING"
    assert value["code"] == code


class _FailedProvider:
    provider_id = "failed"
    provider_version = "1"

    def propose(self, request: ScaffoldRequest) -> ScaffoldProposal:
        raise RuntimeError("must remain redacted")


class _InvalidProvider:
    provider_id = "invalid"
    provider_version = "1"

    def propose(self, request: ScaffoldRequest) -> ScaffoldProposal:
        return ScaffoldProposal("not: DSL", self.provider_id, self.provider_version)


def test_provider_failure_and_invalid_output_are_bounded_without_execution() -> None:
    request = ScaffoldRequest("draft", ("finish",))
    with pytest.raises(ScaffoldProviderFailedError, match="provider failed"):
        scaffold_scenario(request, provider="failed", providers={"failed": _FailedProvider()})
    with pytest.raises(ScaffoldOutputInvalidError, match="ordinary DSE validation"):
        scaffold_scenario(request, provider="invalid", providers={"invalid": _InvalidProvider()})


def test_provider_metadata_has_no_runtime_semantics_and_later_run_is_explicit() -> None:
    result = scaffold_scenario(ScaffoldRequest("draft", ("finish",)))
    compiled = compile_document(parse_yaml(result.proposed_dsl))
    first = run_scenario(compiled, "seed").to_json_bytes()
    altered_metadata = result.to_jsonable() | {"provider": "non-authoritative"}
    assert altered_metadata["provider"] != result.provider
    assert run_scenario(compiled, "seed").to_json_bytes() == first


def test_help_states_offline_nonexecuting_authoring_boundary() -> None:
    result = invoke("scaffold", "--help")
    assert result.returncode == 0
    assert b"offline" in result.stdout
    assert b"never executes" in result.stdout
