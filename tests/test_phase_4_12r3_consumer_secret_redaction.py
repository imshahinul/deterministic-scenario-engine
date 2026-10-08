from __future__ import annotations

import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import subprocess
import sys

from scenario_engine.dsl import compile_document, parse_yaml, run_scenario


ROOT = Path(__file__).parents[1]
SECRET = "plain-λ-\x01-</script>-" + "z" * 4096
REDACTION = {"availability": "redacted", "reason": "configured_secret_key"}
SCENARIO = """dsl_version: 1
scenario: redaction_case
clock: {start: '2026-01-01T00:00:00Z'}
initial_state:
  api_key: placeholder
  nested:
    list:
      - client_secret: placeholder
        visible: retained
  api-key: placeholder
  apiKey: placeholder
  token: placeholder
  access_token: placeholder
  refresh_token: placeholder
  password: placeholder
  passwd: placeholder
  secret: placeholder
  authorization: placeholder
  credential: placeholder
  api_version: v1
  token_count: 2
  password_policy: strict
  secretary: visible
  authorization_status: allowed
steps:
  - id: record
    write:
      api_key: {$literal: placeholder}
    emit:
      - type: audit
        fields: {credential: {$literal: placeholder}, visible: {$literal: retained}}
    transition: null
"""


def invoke(*arguments: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, "-m", "scenario_engine.cli", *arguments], cwd=ROOT,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        env={"PYTHONPATH": str(ROOT / "src")}, timeout=20,
    )


def artifact(tmp_path: Path) -> Path:
    result = run_scenario(compile_document(parse_yaml(SCENARIO)), "redaction-seed")
    value = result.to_jsonable()

    def replace(item: object) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                if key in {
                    "api_key", "client_secret", "api-key", "apiKey", "token",
                    "access_token", "refresh_token", "password", "passwd", "secret",
                    "authorization", "credential",
                }:
                    item[key] = SECRET
                else:
                    replace(child)
        elif isinstance(item, list):
            for child in item:
                replace(child)

    replace(value)
    path = tmp_path / "result.json"
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    return path


def assert_redacted(output: bytes) -> dict[str, object]:
    assert SECRET.encode("utf-8") not in output
    assert b"plain-" not in output and b"</script>" not in output
    decoded = json.loads(output)
    assert "redacted" in output.decode("utf-8")
    return decoded


def section(document: dict[str, object], name: str) -> object:
    sections = document["sections"]
    assert isinstance(sections, list)
    return next(item["evidence"]["value"] for item in sections if item["name"] == name)


def test_json_and_human_inspect_redact_recursively_without_mutating_source(tmp_path: Path) -> None:
    source = artifact(tmp_path)
    before = source.read_bytes()
    digest = hashlib.sha256(before).hexdigest()

    machine = invoke("--json", "inspect", "--kind", "result", str(source))
    human = invoke("inspect", "--kind", "result", str(source))

    assert machine.returncode == human.returncode == 0
    assert machine.stderr == human.stderr == b""
    machine_value = assert_redacted(machine.stdout)
    human_value = assert_redacted(human.stdout)
    assert machine_value == human_value
    state = section(machine_value, "final_state")
    assert state["api_key"] == REDACTION
    assert state["nested"]["list"][0]["client_secret"] == REDACTION
    for key in (
        "api-key", "apiKey", "token", "access_token", "refresh_token", "password",
        "passwd", "secret", "authorization", "credential",
    ):
        assert state[key] == REDACTION
    assert {key: state[key] for key in (
        "api_version", "token_count", "password_policy", "secretary", "authorization_status",
    )} == {
        "api_version": "v1", "token_count": 2, "password_policy": "strict",
        "secretary": "visible", "authorization_status": "allowed",
    }
    assert source.read_bytes() == before
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest


def test_inspect_redaction_is_deterministic_and_preserves_contract(tmp_path: Path) -> None:
    source = artifact(tmp_path)
    outputs = [invoke("--json", "inspect", "--kind", "result", str(source)) for _ in range(2)]
    assert outputs[0].returncode == outputs[1].returncode == 0
    assert outputs[0].stdout == outputs[1].stdout
    value = assert_redacted(outputs[0].stdout)
    assert value["schema_version"] == "inspection.document/1"
    assert value["target_kind"] == "v1_result"
    assert section(value, "scenario_identity")
    assert section(value, "compatibility")


def test_explain_redacts_recorded_patches_and_artifact_metadata_without_mutation(tmp_path: Path) -> None:
    source = artifact(tmp_path)
    before = source.read_bytes()
    result = invoke("--json", "explain", str(source))
    assert result.returncode == 0 and result.stderr == b""
    value = assert_redacted(result.stdout)
    assert value["schema_version"] == "inspection.explanation/1"
    assert any(record["details"].get("patch", {}).get("api_key") == REDACTION
               for record in value["records"])
    assert source.read_bytes() == before


class _Resources(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.active: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if name in {"src", "href"} and value is not None:
                self.active.append((tag, value))


def test_trace_view_redacts_same_projection_and_remains_offline_inert_and_immutable(tmp_path: Path) -> None:
    source = artifact(tmp_path)
    before = source.read_bytes()
    output = tmp_path / "trace.html"
    result = invoke("trace-view", str(source), "--out", str(output))
    rendered = output.read_bytes()
    assert result.returncode == 0 and result.stderr == b""
    assert SECRET.encode("utf-8") not in rendered and b"plain-" not in rendered
    assert b"configured_secret_key" in rendered
    text = rendered.decode("utf-8")
    parser = _Resources()
    parser.feed(text)
    assert parser.active == [] and "<script" not in text.casefold()
    assert "scenario.trace-view/1" in text
    assert source.read_bytes() == before
