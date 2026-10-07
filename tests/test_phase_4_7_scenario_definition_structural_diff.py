from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from scenario_engine.cli import CLIExitCode
from scenario_engine.definition_diff import compare_definitions, render_definition_diff
from scenario_engine.dsl import parse_yaml


ROOT = Path(__file__).parents[1]

BASE = """dsl_version: 1
scenario: shop
clock: {start: '2026-01-01T00:00:00Z'}
initial_state: {total: 0, ready: false}
resources:
  limit: {$literal: 10}
constraints:
  - id: positive_limit
    check: {$gt: [{$resource: limit}, {$literal: 0}]}
invariants:
  - id: total_nonnegative
    check: {$gte: [{$state: total}, {$literal: 0}]}
faults:
  - id: force_total
    enabled: false
    at: before_step
    selector: {step: checkout}
    operator:
      override_write: {path: total, value: {$literal: 3}}
oracle:
  expected: {constraints: [positive_limit], invariants: [total_nonnegative]}
steps:
  - id: prepare
    generate: {amount: {$int: [1, 2]}}
    derive: {next: {$add: [{$state: total}, {$local: amount}]}}
    write: {total: {$derived: next}}
    emit:
      - type: prepared
        fields: {total: {$state: total}}
    transition: checkout
  - id: checkout
    write: {ready: {$literal: true}, total: {$state: total}}
    transition: null
"""


def invoke(*arguments: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, "-m", "scenario_engine.cli", *arguments], cwd=ROOT,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        env={"PYTHONPATH": str(ROOT / "src")},
    )


def write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "right",
    [
        BASE,
        "\n# same definition\n" + BASE.replace("scenario: shop", "scenario: shop # comment"),
        BASE.replace("initial_state: {total: 0, ready: false}", "initial_state: {ready: false, total: 0}"),
    ],
)
def test_identical_formatting_and_key_order_are_zero_change(right: str) -> None:
    result = compare_definitions(parse_yaml(BASE), parse_yaml(right))
    assert result.changes == ()
    assert result.to_jsonable()["summary"]["change_count"] == 0


def test_step_add_remove_and_component_changes_use_semantic_addresses() -> None:
    added = BASE.replace(
        "    transition: checkout\n  - id: checkout",
        "    transition: review\n  - id: review\n    transition: checkout\n  - id: checkout",
    )
    add = compare_definitions(parse_yaml(BASE), parse_yaml(added))
    assert [(item.change_kind.value, item.semantic_path) for item in add.changes] == [
        ("CHANGED", "scenario:/step/prepare/transition/target"),
        ("ADDED", "scenario:/step/review"),
    ]
    remove = compare_definitions(parse_yaml(added), parse_yaml(BASE))
    assert any(item.change_kind.value == "REMOVED" and item.semantic_path == "scenario:/step/review" for item in remove.changes)

    changed = BASE.replace("{$int: [1, 2]}", "{$int: [1, 3]}")
    changed = changed.replace("{$derived: next}", "{$literal: 9}")
    changed = changed.replace("type: prepared", "type: prepared_v2")
    result = compare_definitions(parse_yaml(BASE), parse_yaml(changed))
    assert {item.semantic_path for item in result.changes} == {
        "scenario:/step/prepare/generator/amount",
        "scenario:/step/prepare/write/total",
        "scenario:/step/prepare/emit/emissions",
    }


def test_fault_invariant_oracle_resource_constraint_and_derive_changes() -> None:
    changed = BASE.replace("enabled: false", "enabled: true")
    changed = changed.replace("{$gte: [{$state: total}, {$literal: 0}]}", "{$gte: [{$state: total}, {$literal: 1}]}")
    changed = changed.replace("strict_unexpected", "strict_unexpected")  # no source-layout semantics
    changed = changed.replace("invariants: [total_nonnegative]", "invariants: []")
    changed = changed.replace("{$literal: 10}", "{$literal: 11}")
    changed = changed.replace("{$gt: [{$resource: limit}, {$literal: 0}]}", "{$gte: [{$resource: limit}, {$literal: 0}]}")
    changed = changed.replace("{$add: [{$state: total}, {$local: amount}]}", "{$mul: [{$state: total}, {$local: amount}]}")
    paths = {item.semantic_path for item in compare_definitions(parse_yaml(BASE), parse_yaml(changed)).changes}
    assert paths == {
        "scenario:/constraint/positive_limit", "scenario:/fault/force_total",
        "scenario:/invariant/total_nonnegative", "scenario:/oracle/expectation",
        "scenario:/resource/limit", "scenario:/step/prepare/derive/next",
    }


def test_cli_json_human_determinism_validation_and_shared_change_set(tmp_path: Path) -> None:
    left = write(tmp_path, "left.yaml", BASE)
    right = write(tmp_path, "right.yaml", BASE.replace("enabled: false", "enabled: true"))
    first = invoke("--json", "diff-definition", str(left), str(right))
    second = invoke("--json", "diff-definition", str(left), str(right))
    assert first.returncode == second.returncode == CLIExitCode.SUCCESS
    assert first.stdout == second.stdout and first.stderr == second.stderr == b""
    value = json.loads(first.stdout)
    assert value["schema"] == "scenario.definition-diff/1"
    assert value["summary"]["change_count"] == 1
    assert value["changes"][0]["semantic_path"] == "scenario:/fault/force_total"
    assert not value["changes"][0]["semantic_path"].startswith("$")
    human = invoke("diff-definition", str(left), str(right))
    assert human.returncode == 0 and b"CHANGED scenario:/fault/force_total" in human.stdout
    direct = compare_definitions(parse_yaml(BASE), parse_yaml(right.read_text()))
    assert render_definition_diff(direct).encode() + b"\n" == human.stdout

    invalid = write(tmp_path, "invalid.yaml", "dsl_version: 1\n")
    for arguments in ((str(invalid), str(right)), (str(left), str(invalid))):
        failure = invoke("--json", "diff-definition", *arguments)
        assert failure.returncode == CLIExitCode.VALIDATION and failure.stdout == b""
        assert json.loads(failure.stderr)["schema"] == "scenario.error/1"


def test_existing_execution_diff_help_remains_explicit() -> None:
    artifact_help = invoke("diff", "--help")
    definition_help = invoke("diff-definition", "--help")
    assert artifact_help.returncode == definition_help.returncode == 0
    assert b"artifact" in artifact_help.stdout
    assert b"validated scenario definitions" in definition_help.stdout
    assert b"distinct from 'scenario diff'" in definition_help.stdout
