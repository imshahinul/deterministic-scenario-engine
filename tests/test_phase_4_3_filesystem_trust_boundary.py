from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest

from scenario_engine.cli import CLIExitCode
from scenario_engine.evidence import EvidenceBundle, canonical_evidence_bytes


ROOT = Path(__file__).parents[1]
SCENARIO = """dsl_version: 1
scenario: path_case
clock: {start: '2026-01-01T00:00:00Z'}
initial_state: {}
steps: []
"""


def invoke(*args: str, cwd: Path = ROOT) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, "-m", "scenario_engine.cli", *args], cwd=cwd,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        env={"PYTHONPATH": str(ROOT / "src")},
    )


def assert_path_failure(result: subprocess.CompletedProcess[bytes], reason: bytes, code: int) -> None:
    assert result.returncode == code
    assert result.stdout == b""
    assert result.stderr.startswith(
        b"scenario: error: code=" + reason + b"; category=FILESYSTEM_TRUST_BOUNDARY;"
    )
    assert b"path_kind=local_filesystem" in result.stderr
    assert b"next_action=" in result.stderr
    assert b"Traceback" not in result.stderr


@pytest.fixture
def empty_bundle(tmp_path: Path) -> Path:
    root = tmp_path / "bundle"
    root.mkdir()
    (root / "bundle.json").write_bytes(canonical_evidence_bytes(EvidenceBundle(())))
    return root


def test_evidence_paths_classify_relative_remote_missing_and_valid(
    empty_bundle: Path, tmp_path: Path,
) -> None:
    relative = invoke("verify", "bundle", cwd=tmp_path)
    remote = invoke("verify", "https://example.invalid/evidence")
    missing = invoke("verify", str(tmp_path / "missing"))
    valid = invoke("verify", str(empty_bundle))

    assert_path_failure(relative, b"PATH_NOT_ABSOLUTE", CLIExitCode.SECURITY_OR_BOUND)
    assert_path_failure(remote, b"PATH_REMOTE_FORBIDDEN", CLIExitCode.SECURITY_OR_BOUND)
    assert_path_failure(missing, b"PATH_NOT_FOUND", CLIExitCode.SECURITY_OR_BOUND)
    assert valid.returncode == CLIExitCode.SUCCESS and valid.stderr == b""


def test_composition_outside_allowed_root_is_stably_classified(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside.yaml"
    outside.write_text(SCENARIO, encoding="utf-8")
    result = invoke("validate", str(outside), "--root", str(allowed))
    assert_path_failure(result, b"PATH_OUTSIDE_ALLOWED_ROOT", CLIExitCode.SECURITY_OR_BOUND)


def test_destination_failures_are_bounded_and_valid_destination_is_unchanged(
    empty_bundle: Path, tmp_path: Path,
) -> None:
    relative = invoke("export", str(empty_bundle), "relative-output", cwd=tmp_path)
    remote = invoke("export", str(empty_bundle), "https://example.invalid/output")
    existing_path = tmp_path / "existing"
    existing_path.mkdir()
    existing = invoke("export", str(empty_bundle), str(existing_path))
    missing_parent = invoke("export", str(empty_bundle), str(tmp_path / "missing-parent" / "out"))
    destination = tmp_path / "valid-output"
    valid = invoke("export", str(empty_bundle), str(destination))

    assert_path_failure(relative, b"PATH_NOT_ABSOLUTE", CLIExitCode.SECURITY_OR_BOUND)
    assert_path_failure(remote, b"PATH_REMOTE_FORBIDDEN", CLIExitCode.SECURITY_OR_BOUND)
    assert_path_failure(existing, b"DESTINATION_ALREADY_EXISTS", CLIExitCode.IO)
    assert_path_failure(missing_parent, b"DESTINATION_PARENT_MISSING", CLIExitCode.IO)
    assert valid.returncode == CLIExitCode.SUCCESS and (destination / "bundle.json").is_file()


def test_help_states_absolute_local_filesystem_path_contract() -> None:
    for command in ("export", "verify", "migrate"):
        result = invoke(command, "--help")
        assert result.returncode == CLIExitCode.SUCCESS
        assert b"absolute local filesystem path" in result.stdout


def test_uri_disguise_and_normalized_traversal_remain_closed(tmp_path: Path) -> None:
    uri = invoke("verify", "git+ssh://example.invalid/evidence")
    assert_path_failure(uri, b"PATH_REMOTE_FORBIDDEN", CLIExitCode.SECURITY_OR_BOUND)

    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.yaml"
    outside.write_text(SCENARIO, encoding="utf-8")
    traversal = invoke("validate", str(root / ".." / "outside.yaml"), "--root", str(root))
    assert_path_failure(traversal, b"PATH_OUTSIDE_ALLOWED_ROOT", CLIExitCode.SECURITY_OR_BOUND)
