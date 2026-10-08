from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from scenario_engine.canonical import canonical_scenario_hash
from scenario_engine.diagnostics import semantic_address
from scenario_engine.dsl import (
    DSLCompilationError, DSLResourceLimitError, DSLSchemaError,
    UnsupportedDSL2ExecutionError, compile_document, parse_yaml, run_scenario,
)


ROOT = Path(__file__).parents[1]


def source(actors: str, extra: str = "") -> str:
    return (
        "dsl_version: 2\nscenario: concurrent\n"
        "clock: {start: '2026-01-01T00:00:00Z'}\n"
        "initial_state: {count: 0}\nactors:\n" + actors + extra
    )


def actor(actor_id: str, count: int = 1, *, prefix: str = "step") -> str:
    steps = []
    for index in range(count):
        transition = f"{prefix}{index + 1}" if index + 1 < count else "null"
        steps.append(f"      - {{id: {prefix}{index}, transition: {transition}}}")
    return f"  - id: {actor_id}\n    steps:\n" + "\n".join(steps) + "\n"


def test_valid_multi_actor_order_identity_hash_and_shared_step_names() -> None:
    raw = source(actor("z /%", prefix="same") + actor("alpha", prefix="same"))
    document = parse_yaml(raw)
    compiled = compile_document(document)
    assert [item.actor_id for item in document.actors] == ["alpha", "z /%"]
    assert document.actors[1].address == "scenario:/actor/z%20%2F%25"
    assert semantic_address(("actor", "x")) is None  # reservation remains frozen by default
    assert canonical_scenario_hash(document) == canonical_scenario_hash(
        raw.replace("initial_state: {count: 0}", "initial_state:\n  count: 0")
    )
    assert compiled.document is document


@pytest.mark.parametrize("ids", [("same", "same"), ("é", "e\u0301")])
def test_duplicate_actor_ids_after_canonicalization(ids: tuple[str, str]) -> None:
    with pytest.raises(DSLSchemaError, match="duplicate canonical actor ID"):
        parse_yaml(source(actor(ids[0]) + actor(ids[1])))


def test_duplicate_actor_step_ids_and_cross_actor_scope() -> None:
    duplicate = "  - id: one\n    steps:\n      - {id: é, transition: é}\n      - {id: é, transition: null}\n"
    with pytest.raises(DSLSchemaError, match="duplicate step ID"):
        parse_yaml(source(duplicate))
    valid = compile_document(parse_yaml(source(actor("one") + actor("two"))))
    assert len(valid.actors) == 2


@pytest.mark.parametrize("replacement", [
    "actors:\n  - id: one\n    steps: [{id: '.', transition: null}]\n",
    "actors:\n  - id: '..'\n    steps: [{id: done, transition: null}]\n",
    "actors:\n  - id: one\n    steps: [{id: done, transition: missing}]\n",
])
def test_malformed_identifiers_and_actor_scoped_references(replacement: str) -> None:
    raw = source(actor("one"))
    raw = raw[:raw.index("actors:\n")] + replacement
    error = (DSLSchemaError if "missing" not in replacement else DSLCompilationError)
    with pytest.raises(error):
        compile_document(parse_yaml(raw))


@pytest.mark.parametrize("mutation", [
    lambda raw: raw.replace("scenario: concurrent\n", ""),
    lambda raw: raw + "unknown: true\n",
    lambda raw: raw.replace("    steps:", "    unknown: true\n    steps:"),
    lambda raw: raw.replace("actors:\n", "steps: []\nactors:\n"),
])
def test_missing_unknown_and_mixed_fields_fail_closed(mutation) -> None:
    with pytest.raises(DSLSchemaError):
        parse_yaml(mutation(source(actor("one"))))


def test_inclusive_actor_and_step_boundaries() -> None:
    assert len(parse_yaml(source("".join(actor(f"a{i}") for i in range(32)))).actors) == 32
    with pytest.raises(DSLResourceLimitError, match="MAX_ACTORS"):
        parse_yaml(source("".join(actor(f"a{i}") for i in range(33))))
    assert len(parse_yaml(source(actor("one", 256))).actors[0].steps) == 256
    with pytest.raises(DSLResourceLimitError, match="MAX_STEPS_PER_ACTOR"):
        parse_yaml(source(actor("one", 257)))


def test_aggregate_boundary_and_limit_interaction_are_structurally_feasible() -> None:
    exact = parse_yaml(source("".join(actor(f"a{i}", 256, prefix=f"s{i}_") for i in range(16))))
    assert sum(len(item.steps) for item in exact.actors) == 4096
    over = "".join(actor(f"a{i}", 256, prefix=f"s{i}_") for i in range(16)) + actor("extra")
    with pytest.raises(DSLResourceLimitError, match="MAX_TOTAL_DECLARED_STEPS"):
        parse_yaml(source(over))
    # 4097 in one actor is intentionally not asserted: the per-actor ceiling rejects first.


def test_run_is_explicitly_unsupported_without_actor_execution() -> None:
    compiled = compile_document(parse_yaml(source(actor("one"))))
    with pytest.raises(UnsupportedDSL2ExecutionError, match="not implemented"):
        run_scenario(compiled, "seed")


def invoke(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, "-m", "scenario_engine.cli", *args], cwd=ROOT,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        env={"PYTHONPATH": str(ROOT / "src")},
    )


def test_cli_validate_pass_run_unsupported_and_error_envelope(tmp_path: Path) -> None:
    path = tmp_path / "dsl2.yaml"; path.write_text(source(actor("one")), encoding="utf-8")
    valid = invoke("--json", "validate", str(path))
    assert valid.returncode == 0 and json.loads(valid.stdout)["valid"] is True
    run = invoke("--json", "run", str(path), "--seed", "seed")
    envelope = json.loads(run.stderr)
    assert run.returncode == 4 and envelope["schema"] == "scenario.error/1"
    assert envelope["code"] == "DSL2_EXECUTION_UNSUPPORTED"


def test_cli_input_bound_remains_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "oversized.yaml"; path.write_bytes(b"x" * (16 * 1024 * 1024 + 1))
    result = invoke("--json", "validate", str(path))
    assert result.returncode == 6 and b"Traceback" not in result.stderr
