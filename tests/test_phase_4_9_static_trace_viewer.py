from __future__ import annotations

from html.parser import HTMLParser
import json
from pathlib import Path
import subprocess
import sys

import pytest

from scenario_engine.cli import CLIExitCode
from scenario_engine.dsl import compile_document, parse_yaml, run_scenario
from scenario_engine.suite import read_v1_result_bytes
from scenario_engine.trace_view import TraceViewError, render_trace_view


ROOT = Path(__file__).parents[1]
SCENARIO = """dsl_version: 1
scenario: trace_case
clock: {start: '2026-01-01T00:00:00Z'}
initial_state: {count: 0}
invariants:
  - id: nonnegative
    check: {$gte: [{$state: count}, {$literal: 0}]}
steps:
  - id: increment
    write: {count: {$literal: 1}}
    emit:
      - type: audit
        fields: {count: {$state: count}}
    transition: null
"""


def invoke(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, "-m", "scenario_engine.cli", *args], cwd=ROOT,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        env={"PYTHONPATH": str(ROOT / "src")},
    )


class _Resources(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.active: list[tuple[str, str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        for attribute in ("src", "href"):
            value = values.get(attribute)
            if value is not None:
                self.active.append((tag, attribute, value))


@pytest.fixture
def result_file(tmp_path: Path) -> Path:
    result = run_scenario(compile_document(parse_yaml(SCENARIO)), "trace-seed")
    path = tmp_path / "result.json"
    path.write_bytes(result.to_json_bytes())
    return path


def test_valid_result_generates_one_deterministic_offline_file(
    result_file: Path, tmp_path: Path,
) -> None:
    source_before = result_file.read_bytes()
    first = tmp_path / "first.html"
    second = tmp_path / "second.html"
    one = invoke("trace-view", str(result_file), "--out", str(first))
    two = invoke("trace-view", str(result_file), "--out", str(second))

    assert one.returncode == two.returncode == CLIExitCode.SUCCESS
    assert first.read_bytes() == second.read_bytes()
    assert result_file.read_bytes() == source_before
    assert sorted(path.name for path in tmp_path.iterdir()) == ["first.html", "result.json", "second.html"]
    text = first.read_text(encoding="utf-8")
    for expected in (
        "scenario.trace-view/1", "trace_case", "1.0.0", "DSL version", "trace-seed",
        "Authoritative step timeline", "increment", "state before fingerprint",
        "observed state patch", "state after fingerprint", "faults applied",
        "Emitted artifacts", "nonnegative", "scenario_canonical_hash",
    ):
        assert expected in text
    parser = _Resources()
    parser.feed(text)
    assert parser.active == []
    assert "<script" not in text.casefold()
    assert all(marker not in text for marker in ("fetch(", "XMLHttpRequest", "WebSocket", "EventSource", "google-analytics", "telemetry"))


def test_evidence_markup_and_script_boundary_are_inert(tmp_path: Path) -> None:
    result = run_scenario(compile_document(parse_yaml(SCENARIO)), "seed").to_jsonable()
    result["scenario_id"] = '</script><script>globalThis.compromised=true</script><img src="https://bad.invalid/x">'
    source = tmp_path / "malicious.json"
    source.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    output = tmp_path / "safe.html"

    completed = invoke("trace-view", str(source), "--out", str(output))
    text = output.read_text(encoding="utf-8")
    parser = _Resources()
    parser.feed(text)
    assert completed.returncode == 0
    assert "</script><script>" not in text
    assert "&lt;/script&gt;&lt;script&gt;" in text
    assert parser.active == []


def test_suite_run_without_timeline_reports_only_available_evidence(tmp_path: Path) -> None:
    scenario = tmp_path / "scenario.yaml"
    replay = tmp_path / "run.json"
    output = tmp_path / "run.html"
    scenario.write_text(SCENARIO, encoding="utf-8")
    assert invoke("run", str(scenario), "--seed", "seed", "--replay-out", str(replay)).returncode == 0
    assert invoke("trace-view", str(replay), "--out", str(output)).returncode == 0
    text = output.read_text(encoding="utf-8")
    assert "suite.run/1" in text and "trace_case" in text
    assert "not present in artifact" in text


def test_unsupported_remote_existing_and_oversized_inputs_fail_bounded(
    result_file: Path, tmp_path: Path,
) -> None:
    unsupported = tmp_path / "unsupported.json"
    unsupported.write_text('{"unknown":true}', encoding="utf-8")
    invalid = invoke("--json", "trace-view", str(unsupported), "--out", str(tmp_path / "bad.html"))
    envelope = json.loads(invalid.stderr)
    assert invalid.returncode == CLIExitCode.VALIDATION and invalid.stdout == b""
    assert envelope["schema"] == "scenario.error/1" and envelope["code"] == "TRACE_INPUT_UNSUPPORTED"

    remote = invoke("--json", "trace-view", "https://example.invalid/result", "--out", str(tmp_path / "remote.html"))
    assert remote.returncode == CLIExitCode.SECURITY_OR_BOUND
    assert json.loads(remote.stderr)["code"] == "PATH_REMOTE_FORBIDDEN"

    existing = tmp_path / "existing.html"
    existing.write_bytes(b"preserve")
    rejected = invoke("trace-view", str(result_file), "--out", str(existing))
    assert rejected.returncode == CLIExitCode.IO and existing.read_bytes() == b"preserve"

    huge = tmp_path / "huge.json"
    huge.write_bytes(b" " * (16 * 1024 * 1024 + 1))
    oversized = invoke("--json", "trace-view", str(huge), "--out", str(tmp_path / "huge.html"))
    assert oversized.returncode == CLIExitCode.SECURITY_OR_BOUND
    assert json.loads(oversized.stderr)["code"] == "TRACE_INPUT_TOO_LARGE"
    assert not (tmp_path / "huge.html").exists()


def test_output_bound_fails_before_publication(monkeypatch: pytest.MonkeyPatch) -> None:
    import scenario_engine.trace_view as module

    artifact = read_v1_result_bytes(run_scenario(compile_document(parse_yaml(SCENARIO)), "seed").to_json_bytes())
    monkeypatch.setattr(module, "TRACE_VIEW_MAX_OUTPUT_BYTES", 32)
    with pytest.raises(TraceViewError) as captured:
        render_trace_view(artifact)
    assert captured.value.code == "TRACE_OUTPUT_TOO_LARGE"


def test_help_freezes_local_read_only_boundary() -> None:
    result = invoke("trace-view", "--help")
    assert result.returncode == 0
    for phrase in (b"absolute local", b"one read-only", b"HTML file", b"No server", b"network", b"telemetry", b"source mutation"):
        assert phrase in result.stdout
