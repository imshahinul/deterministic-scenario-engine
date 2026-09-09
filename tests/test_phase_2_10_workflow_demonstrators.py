from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys

import yaml


ROOT = Path(__file__).parents[1]
WORKFLOW = ROOT / ".github/workflows/scenario-engine.yml"


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _invoke(*args: str, source_root: Path = ROOT) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, "-m", "scenario_engine.cli", "--json", *args],
        cwd=source_root,
        env={"PYTHONPATH": str(source_root / "src")},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def test_workflow_is_bounded_parseable_and_non_privileged() -> None:
    text = _workflow_text()
    document = yaml.load(text, Loader=yaml.BaseLoader)
    assert document["name"] == "Deterministic scenario evidence"
    assert set(document["on"]) == {"push", "pull_request", "workflow_dispatch"}
    job = document["jobs"]["scenario-evidence"]
    assert job["timeout-minutes"] == "10"
    assert document["permissions"] == {"contents": "read"}
    assert job["runs-on"] == "ubuntu-latest"
    assert len(job["steps"]) == 5
    assert "/Users/" not in text and "$HOME" not in text
    assert "secrets." not in text and "${{ env." not in text
    assert not re.search(r"\b(publish|release|git tag|git push)\b", text, re.IGNORECASE)


def test_workflow_uses_only_public_product_surfaces_with_explicit_coordinates() -> None:
    text = _workflow_text()
    for command in ("validate", "run", "hash", "inspect", "diff", "replay", "matrix", "batch"):
        assert f"scenario --json {command}" in text
    assert "from scenario_engine.suite import" in text
    assert "scenario_engine._" not in text and "src/scenario_engine" not in text
    assert "--seed phase-2-10-ci" in text
    assert "--run-index 0" in text and "--locale en_US" in text
    assert "--workers 2 --max-in-flight 2" in text
    assert "random" not in text.lower() and "datetime.now" not in text
    assert "date +" not in text and "time.time" not in text
    assert "importlib" not in text and "entry_points" not in text
    assert "curl " not in text and "wget " not in text


def test_repeated_public_cli_execution_is_byte_identical_and_diff_detects_change(tmp_path: Path) -> None:
    args = (
        "run", "examples/cart.yaml", "--seed", "phase-2-10-ci",
        "--run-index", "0", "--locale", "en_US",
    )
    first, second = _invoke(*args), _invoke(*args)
    assert first.returncode == second.returncode == 0
    assert first.stderr == second.stderr == b""
    assert first.stdout == second.stdout

    left = tmp_path / "left.json"
    right = tmp_path / "right.json"
    left.write_bytes(first.stdout)
    changed = _invoke(
        "run", "examples/cart.yaml", "--seed", "phase-2-10-ci",
        "--run-index", "1", "--locale", "en_US",
    )
    assert changed.returncode == 0
    right.write_bytes(changed.stdout)
    different = _invoke("diff", str(left), str(right), "--mode", "first")
    assert different.returncode == 1 and different.stderr == b""
    payload = json.loads(different.stdout)
    assert payload["equal"] is False and len(payload["records"]) == 1


def test_fresh_tree_wheel_supports_workflow_public_commands(tmp_path: Path) -> None:
    archive = tmp_path / "source.tar"
    subprocess.run(
        ["git", "archive", "--format=tar", "HEAD", "-o", str(archive)],
        cwd=ROOT,
        check=True,
    )
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    subprocess.run(["tar", "-xf", str(archive), "-C", str(fresh)], check=True)
    # Include the uncommitted Phase 2.10 workflow for the pre-commit simulation.
    workflow = fresh / WORKFLOW.relative_to(ROOT)
    workflow.parent.mkdir(parents=True, exist_ok=True)
    workflow.write_bytes(WORKFLOW.read_bytes())

    wheelhouse = tmp_path / "wheelhouse"
    subprocess.run(
        [sys.executable, "-m", "pip", "wheel", "--no-deps", "-w", str(wheelhouse), "."],
        cwd=fresh,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    wheel = next(wheelhouse.glob("deterministic_scenario_engine-1.0.0-*.whl"))
    installed = tmp_path / "installed"
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--no-deps", "--target", str(installed), str(wheel)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    env = {"PYTHONPATH": str(installed)}
    validate = subprocess.run(
        [sys.executable, "-m", "scenario_engine.cli", "--json", "validate", "examples/cart.yaml"],
        cwd=fresh,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    semantic_hash = subprocess.run(
        [sys.executable, "-m", "scenario_engine.cli", "--json", "hash", "examples/cart.yaml"],
        cwd=fresh,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert validate.returncode == semantic_hash.returncode == 0
    assert json.loads(validate.stdout)["valid"] is True
    assert json.loads(validate.stdout)["identity"] == json.loads(semantic_hash.stdout)["hash"]


def test_workflow_artifacts_are_logical_and_safety_policy_is_preserved() -> None:
    text = _workflow_text()
    expected = {
        "validation.json", "semantic-hash.json", "result.json", "inspection.json",
        "equal-diff.json", "replay-manifest.json", "replay-result.json", "matrix.json",
        "matrix-result.json", "batch-plan.json", "batch-result.json", "different-diff.json",
    }
    assert all(f"artifacts/{name}" in text for name in expected)
    assert "actions/upload-artifact@v4" in text
    assert "retention-days: 7" in text
    forbidden = ("eval ", "exec ", "python -m build --sdist", "twine", "gh release", "docker push")
    assert all(token not in text for token in forbidden)
    assert "optional_demonstrator" not in text
