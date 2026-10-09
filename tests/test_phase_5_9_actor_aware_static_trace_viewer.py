from __future__ import annotations

from dataclasses import replace
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from scenario_engine.engine2 import canonical_result2_bytes, construct_result2, execute_engine2, validate_engine2
from scenario_engine.schedule import canonical_schedule_bytes
from scenario_engine.trace_view import TraceViewError, render_trace_view


ROOT = Path(__file__).parents[1]
SCENARIO = """dsl_version: 2
scenario: actor-view
clock: {start: '2026-01-01T00:00:00Z'}
initial_state: {count: 0, observed: -1, token: hidden}
actors:
  - id: z_writer
    steps:
      - id: write
        write: {count: {$add: [{$state: count}, {$literal: 1}]}}
        advance: {seconds: 1}
        emit:
          - type: audit
            fields: {hostile: {$literal: '</script><script>alert(1)</script><img src="javascript:bad">'}}
        transition: null
  - id: a_reader
    steps:
      - id: read
        write: {observed: {$state: count}}
        transition: null
"""


def produced(source: str = SCENARIO, seed: int = 7):
    return execute_engine2(validate_engine2(source), "generation", seed)


def invoke(*arguments: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[bytes]:
    actual = os.environ.copy()
    actual["PYTHONPATH"] = str(ROOT / "src")
    if env:
        actual.update(env)
    return subprocess.run([sys.executable, "-m", "scenario_engine.cli", *arguments], cwd=ROOT,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, env=actual)


class Resources(HTMLParser):
    def __init__(self) -> None:
        super().__init__(); self.active: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        for key in ("src", "href", "action"):
            if values.get(key) is not None: self.active.append((key, values[key] or ""))


def test_t01_t06_actor_lanes_global_order_selection_commit_distinction() -> None:
    result, schedule = produced()
    text = render_trace_view(result, schedule=schedule).decode()
    assert text.index("scenario:/actor/a_reader</h3>") < text.index("scenario:/actor/z_writer</h3>")
    for index, event in enumerate(result.history):
        marker = f"<code>{index}</code>"
        assert marker in text and event["actor"] in text and event["address"] in text
    assert "Global committed-history timeline" in text and "Actor lanes" in text
    assert "selection ordinal" in text and "global history index" in text
    assert "shared-state change" in text and "logical clock" in text


def test_t07_t17_failed_attempt_has_no_fabricated_commit_and_terminal_failure() -> None:
    source = SCENARIO + "invariants:\n  - id: impossible\n    check: {$lte: [{$state: count}, {$literal: 0}]}\n"
    scenario = validate_engine2(source)
    for seed in range(50):
        try:
            execute_engine2(scenario, "generation", seed)
        except Exception as error:
            outcome = getattr(error, "internal_outcome", None)
            if outcome is None: continue
            result = construct_result2(scenario, outcome)
            html = render_trace_view(result, schedule=outcome.schedule).decode()
            assert html.count("transition status</dt><dd><code>COMMITTED") == 2 * len(result.history)
            assert "selection outcome</dt><dd><code>FAILED" in html
            assert "InvariantViolation" in html and result.classification == "FAILED"
            return
    pytest.fail("no bounded failing schedule")


def test_t08_t12_schedule_context_missing_corrupt_and_mismatch(tmp_path: Path) -> None:
    result, schedule = produced()
    absent = render_trace_view(result).decode()
    assert "no schedule evidence supplied; no ready sets or ordinals inferred" in absent
    assert "exact execution replay</dt><dd><code>not performed" in absent
    mismatch_result, mismatch = produced(seed=8)
    assert mismatch_result.schedule_reference.schedule_hash != result.schedule_reference.schedule_hash
    with pytest.raises(TraceViewError, match="schedule does not match"):
        render_trace_view(result, schedule=mismatch)
    result_path = tmp_path / "result.json"; result_path.write_bytes(canonical_result2_bytes(result))
    bad = tmp_path / "bad.json"; bad.write_bytes(canonical_schedule_bytes(schedule) + b" ")
    output = tmp_path / "bad.html"
    completed = invoke("--json", "trace-view", str(result_path), "--schedule", str(bad), "--out", str(output))
    assert completed.returncode != 0 and not output.exists()
    assert json.loads(completed.stderr)["code"] == "TRACE_SCHEDULE_INVALID"


def test_t18_t27_integrity_redaction_injection_offline_readonly_and_determinism(tmp_path: Path) -> None:
    result, schedule = produced()
    result_before = canonical_result2_bytes(result); schedule_before = canonical_schedule_bytes(schedule)
    first = render_trace_view(result, schedule=schedule); second = render_trace_view(result, schedule=schedule)
    assert first == second and canonical_result2_bytes(result) == result_before
    assert canonical_schedule_bytes(schedule) == schedule_before
    text = first.decode(); parser = Resources(); parser.feed(text)
    assert "hidden" not in text and "configured_secret_key" in text
    assert "</script><script>" not in text and "&lt;/script&gt;&lt;script&gt;" in text
    assert "javascript:bad" in text and parser.active == [] and "<script" not in text.casefold()
    assert "default-src 'none'" in text and all(marker not in text for marker in ("https://", "http://", "fetch("))


def test_t28_cross_process_stability_and_t43_fixed_independent_golden() -> None:
    code = f'''from scenario_engine.engine2 import execute_engine2,validate_engine2\nfrom scenario_engine.trace_view import render_trace_view\nr,s=execute_engine2(validate_engine2({SCENARIO!r}),"generation",7);print(render_trace_view(r,schedule=s).hex())'''
    outputs = []
    for seed in ("1", "999"):
        env = os.environ.copy(); env.update({"PYTHONPATH": str(ROOT / "src"), "PYTHONHASHSEED": seed})
        outputs.append(subprocess.check_output([sys.executable, "-c", code], cwd=ROOT, env=env))
    assert outputs[0] == outputs[1]
    assert hashlib.sha256(bytes.fromhex(outputs[0].decode().strip())).hexdigest() == "f2cc84646e73b3889d3ca1db629ece40669267902c17a22671b34703c5956e57"


def test_t30_t35_strict_readers_unknown_contract_destination_and_legacy(tmp_path: Path) -> None:
    result, schedule = produced()
    result_path = tmp_path / "result.json"; result_path.write_bytes(canonical_result2_bytes(result))
    schedule_path = tmp_path / "schedule.json"; schedule_path.write_bytes(canonical_schedule_bytes(schedule))
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_bytes(result_path.read_bytes().replace(b'{"actors":', b'{"actors":[],"actors":', 1))
    assert invoke("trace-view", str(duplicate), "--out", str(tmp_path / "duplicate.html")).returncode != 0
    unknown = tmp_path / "unknown.json"; unknown.write_text('{"contract":"scenario.result/999"}')
    assert invoke("trace-view", str(unknown), "--out", str(tmp_path / "unknown.html")).returncode != 0
    existing = tmp_path / "existing.html"; existing.write_bytes(b"preserve")
    assert invoke("trace-view", str(result_path), "--schedule", str(schedule_path), "--out", str(existing)).returncode != 0
    assert existing.read_bytes() == b"preserve"


def test_t44_t46_public_cli_python_and_offline_file(tmp_path: Path) -> None:
    result, schedule = produced()
    source = tmp_path / "result.json"; source.write_bytes(canonical_result2_bytes(result))
    scheduled = tmp_path / "schedule.json"; scheduled.write_bytes(canonical_schedule_bytes(schedule))
    output = tmp_path / "view.html"
    completed = invoke("--json", "trace-view", str(source), "--schedule", str(scheduled), "--out", str(output))
    assert completed.returncode == 0 and json.loads(completed.stdout)["contract"] == "scenario.trace-view/1"
    assert output.read_bytes().startswith(b"<!doctype html>")
