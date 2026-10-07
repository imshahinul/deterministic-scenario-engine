from __future__ import annotations

from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).parents[1]
QUICKSTART = ROOT / "docs/quickstart.md"


def invoke(*arguments: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, "-m", "scenario_engine.cli", *arguments],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        env={"PYTHONPATH": str(ROOT / "src")},
    )


def test_canonical_workflow_document_freezes_public_command_shapes() -> None:
    text = QUICKSTART.read_text(encoding="utf-8")
    shapes = (
        'scenario validate "$DSE_DEMO/scenario.yaml"',
        'scenario --json run "$DSE_DEMO/scenario.yaml" --seed demo-seed --run-index 0 --replay-out "$DSE_DEMO/replay.json"',
        'scenario --json replay "$DSE_DEMO/replay.json" --scenario "$DSE_DEMO/scenario.yaml"',
        'scenario --json inspect "$DSE_DEMO/result.json" --kind result',
        'scenario --json explain "$DSE_DEMO/result.json"',
        'scenario --json diff "$DSE_DEMO/result.json" "$DSE_DEMO/result-after.json" --kind result --mode complete',
        'scenario --json diff-definition "$DSE_DEMO/scenario-before.yaml" "$DSE_DEMO/scenario-after.yaml"',
        'scenario --json impact "$DSE_DEMO/scenario-before.yaml" "$DSE_DEMO/scenario-after.yaml"',
        'scenario export "$DSE_DEMO/evidence" "$DSE_DEMO/evidence-copy"',
        'scenario verify "$DSE_DEMO/evidence-copy"',
        'scenario trace-view "$DSE_DEMO/result.json" --out "$DSE_DEMO/trace.html"',
        "scenario scaffold reviewed_draft --step prepare --step finish",
    )
    assert all(shape in text for shape in shapes)
    for identity in (
        "scenario.semantic-address/1", "scenario.error/1", "scenario.scaffold/1",
        "scenario.definition-diff/1", "scenario.impact/1", "scenario.trace-view/1",
        "suite.run/1",
    ):
        assert identity in text


def test_top_level_and_phase4_command_help_are_coherent() -> None:
    top = invoke("--help")
    assert top.returncode == 0
    for command in (
        b"validate", b"run", b"replay", b"inspect", b"explain", b"diff",
        b"diff-definition", b"impact", b"export", b"verify", b"trace-view", b"scaffold",
    ):
        assert command in top.stdout
    checks = {
        "run": (b"scenario.result/1", b"suite.run/1", b"not automatically replayable"),
        "replay": (b"suite.run/1", b"stable replay reason code"),
        "diff-definition": (b"structurally", b"scenario.semantic-address/1", b"does not run impact"),
        "impact": (b"DIRECT", b"TRANSITIVE_POSSIBLE", b"UNKNOWN does not mean unaffected", b"not a probability"),
        "scaffold": (b"offline", b"No API key", b"runtime LLM", b"never executes", b"untrusted"),
        "trace-view": (b"absolute local", b"one read-only", b"No server", b"network", b"telemetry"),
    }
    for command, phrases in checks.items():
        result = invoke(command, "--help")
        assert result.returncode == 0
        assert all(phrase in result.stdout for phrase in phrases)


def test_public_docs_have_no_checkpoint_or_checkout_dependency() -> None:
    docs = (ROOT / "README.md").read_text() + QUICKSTART.read_text()
    forbidden = (
        "/Users/", "scenario-engine-audit", "unreleased", "not yet published",
        "current unreleased build", "$HOME/Developer/scenario-engine",
        "UNKNOWN means unaffected", "scaffold auto-executes",
    )
    assert all(item not in docs for item in forbidden)
    assert "Installed-package workflows are primary" in docs
