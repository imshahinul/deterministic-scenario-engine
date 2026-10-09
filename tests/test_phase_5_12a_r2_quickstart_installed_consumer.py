from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
DSL1 = """dsl_version: 1
scenario: dse_demo
clock: {start: '2026-01-01T00:00:00Z'}
initial_state: {count: 0}
steps:
  - id: increment
    write: {count: {$literal: 1}}
    emit:
      - type: count_changed
        fields: {count: {$state: count}}
    transition: null
"""
DSL2 = """dsl_version: 2
scenario: dse_actor_demo
clock: {start: '2026-01-01T00:00:00Z'}
initial_state: {count: 0, observed: -1}
actors:
  - id: writer
    steps:
      - id: increment
        write: {count: {$add: [{$state: count}, {$literal: 1}]}}
        transition: null
  - id: reader
    steps:
      - id: observe
        write: {observed: {$state: count}}
        transition: null
"""


def test_complete_quickstart_from_fresh_installed_wheel(tmp_path: Path) -> None:
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    built = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation",
         "--wheel-dir", str(wheelhouse), str(ROOT)],
        cwd=tmp_path, capture_output=True, check=False,
    )
    assert built.returncode == 0, built.stderr.decode(errors="replace")
    wheels = list(wheelhouse.glob("deterministic_scenario_engine-*.whl"))
    assert len(wheels) == 1

    installed_root = tmp_path / "installed"
    installed = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--no-deps", "--target",
         str(installed_root), str(wheels[0])],
        cwd=tmp_path, capture_output=True, check=False,
    )
    assert installed.returncode == 0, installed.stderr.decode(errors="replace")
    python = Path(sys.executable)
    demo = tmp_path / "dse-demo"
    demo.mkdir()
    clean_env = os.environ.copy()
    clean_env["PYTHONPATH"] = str(installed_root)

    def run(*arguments: str, stdout: Path | None = None, expected: int = 0) -> subprocess.CompletedProcess[bytes]:
        completed = subprocess.run(
            [str(python), "-m", "scenario_engine.cli", *arguments], cwd=demo, env=clean_env,
            capture_output=True, check=False,
        )
        if stdout is not None:
            stdout.write_bytes(completed.stdout)
        assert completed.returncode == expected, completed.stderr.decode(errors="replace")
        return completed

    identity = subprocess.run(
        [str(python), "-c", "import scenario_engine; print(scenario_engine.__file__)"],
        cwd=demo, env=clean_env, capture_output=True, text=True, check=True,
    )
    assert Path(identity.stdout.strip()).is_relative_to(installed_root)
    run("--help")

    # Existing documented DSL 1 journey.
    source = demo / "scenario.yaml"
    source.write_text(DSL1, encoding="utf-8")
    (demo / "scenario-before.yaml").write_bytes(source.read_bytes())
    (demo / "scenario-after.yaml").write_text(
        DSL1.replace("{$literal: 1}", "{$literal: 2}"), encoding="utf-8",
    )
    run("validate", str(source))
    result1 = demo / "result.json"
    replay1 = demo / "replay.json"
    run("--json", "run", str(source), "--seed", "demo-seed", "--run-index", "0",
        "--replay-out", str(replay1), stdout=result1)
    replayed1 = demo / "replayed-result.json"
    run("--json", "replay", str(replay1), "--scenario", str(source), stdout=replayed1)
    assert json.loads(result1.read_bytes()) == json.loads(replayed1.read_bytes())

    # Documented DSL 2 creation, validation, persistence, canonical comparison, and exact replay.
    actors = demo / "actors.yaml"
    actors.write_text(DSL2, encoding="utf-8")
    run("validate", str(actors))
    schedule = demo / "schedule.json"
    result2 = demo / "result-v2.json"
    executed = run("--json", "run", str(actors), "--seed", "generation-seed",
        "--schedule-seed", "7", "--run-index", "0", "--schedule-out", str(schedule),
        "--result-out", str(result2))
    assert executed.stdout.rstrip(b"\n") == result2.read_bytes()
    assert json.loads(result2.read_bytes())["contract"] == "scenario.result/2"
    assert json.loads(schedule.read_bytes())["contract"] == "scenario.schedule/1"
    replayed2 = demo / "replayed-result-v2.json"
    run("--json", "replay", str(result2), "--scenario", str(actors),
        "--schedule", str(schedule), stdout=replayed2)
    assert json.loads(result2.read_bytes()) == json.loads(replayed2.read_bytes())

    run("--json", "inspect", str(result1), "--kind", "result", stdout=demo / "inspection.json")
    run("--json", "explain", str(result1), stdout=demo / "explanation.json")
    inspection2 = demo / "inspection-v2.json"
    explanation2 = demo / "explanation-v2.json"
    run("--json", "inspect", str(result2), "--kind", "result", stdout=inspection2)
    run("--json", "explain", str(result2), "--schedule", str(schedule),
        "--actor", "scenario:/actor/writer", stdout=explanation2)
    assert json.loads(inspection2.read_bytes())["schema_version"] == "inspection.document/2"
    assert json.loads(explanation2.read_bytes())["schema_version"] == "inspection.explanation/2"

    after_result = demo / "result-after.json"
    run("--json", "run", str(demo / "scenario-after.yaml"), "--seed", "demo-seed", stdout=after_result)
    run("--json", "diff", str(result1), str(after_result), "--kind", "result", "--mode", "complete",
        stdout=demo / "execution-diff.json", expected=1)
    run("--json", "diff-definition", str(demo / "scenario-before.yaml"),
        str(demo / "scenario-after.yaml"), stdout=demo / "definition-diff.json")
    run("--json", "impact", str(demo / "scenario-before.yaml"),
        str(demo / "scenario-after.yaml"), stdout=demo / "impact.json")

    export_code = (
        "from pathlib import Path; from scenario_engine.reference_packs import export_ecommerce_evidence; "
        f"export_ecommerce_evidence(Path({str(demo / 'evidence')!r}))"
    )
    subprocess.run([str(python), "-c", export_code], cwd=demo, env=clean_env, check=True)
    run("verify", str(demo / "evidence"))
    run("export", str(demo / "evidence"), str(demo / "evidence-copy"))
    run("verify", str(demo / "evidence-copy"))

    run("trace-view", str(result1), "--out", str(demo / "trace.html"))
    run("trace-view", str(result2), "--schedule", str(schedule), "--out", str(demo / "trace-v2.html"))
    assert (demo / "trace.html").read_bytes().startswith(b"<!doctype html>")
    assert (demo / "trace-v2.html").read_bytes().startswith(b"<!doctype html>")

    draft = demo / "draft.yaml"
    run("scaffold", "reviewed_draft", "--step", "prepare", "--step", "finish", stdout=draft)
    run("validate", str(draft))
    run("--json", "run", str(draft), "--seed", "reviewed-seed", stdout=demo / "draft-result.json")

    fixtures = demo / "phase5_10-fixtures"
    run("compatibility-fixtures", "export", "--pack", "phase5_10", "--out", str(fixtures))
    fixture_replay = run("--json", "replay", str(fixtures / "artifacts/result-v2.json"),
        "--scenario", str(fixtures / "scenarios/scenario-v2.yaml"),
        "--schedule", str(fixtures / "artifacts/schedule-v1.json"))
    assert json.loads(fixture_replay.stdout)["contract"] == "scenario.result/2"

    # The fresh directory contains only declared inputs, command outputs, and exported trees.
    declared_roots = {
        "actors.yaml", "draft-result.json", "draft.yaml", "evidence", "evidence-copy",
        "execution-diff.json", "explanation-v2.json", "explanation.json", "impact.json",
        "inspection-v2.json", "inspection.json", "phase5_10-fixtures", "replay.json",
        "replayed-result-v2.json", "replayed-result.json", "result-after.json", "result-v2.json",
        "result.json", "scenario-after.yaml", "scenario-before.yaml", "scenario.yaml",
        "schedule.json", "trace-v2.html", "trace.html", "definition-diff.json",
    }
    assert {path.name for path in demo.iterdir()} == declared_roots
