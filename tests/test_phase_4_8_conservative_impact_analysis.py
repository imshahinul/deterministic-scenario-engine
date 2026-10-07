from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from scenario_engine.cli import CLIExitCode
from scenario_engine.definition_diff import compare_definitions
from scenario_engine.dsl import parse_yaml
from scenario_engine.impact import ImpactClassification, analyze_impact


ROOT = Path(__file__).parents[1]
BASE = """dsl_version: 1
scenario: impact
clock: {start: '2026-01-01T00:00:00Z'}
initial_state: {total: 0}
resources: {limit: {$literal: 10}}
constraints:
  - id: valid_limit
    check: {$gt: [{$resource: limit}, {$literal: 0}]}
invariants:
  - id: total_valid
    check: {$gte: [{$state: total}, {$literal: 0}]}
oracle:
  expected: {constraints: [valid_limit], invariants: [total_valid]}
steps:
  - id: calculate
    generate: {amount: {$int: [1, 2]}}
    derive: {next: {$add: [{$state: total}, {$local: amount}]}}
    write: {total: {$derived: next}}
    emit:
      - type: calculated
        fields: {total: {$state: total}}
    transition: finish
  - id: finish
    transition: null
"""


def invoke(*arguments: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run([sys.executable, "-m", "scenario_engine.cli", *arguments], cwd=ROOT,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
                          env={"PYTHONPATH": str(ROOT / "src")})


def test_change_flows_through_derive_write_state_invariant_and_emission() -> None:
    right = BASE.replace("{$int: [1, 2]}", "{$int: [1, 3]}")
    left_document, right_document = parse_yaml(BASE), parse_yaml(right)
    difference = compare_definitions(left_document, right_document)
    result = analyze_impact(left_document, right_document, difference)
    by_path = {record.affected_semantic_path: record.classification for record in result.records}
    assert by_path["scenario:/step/calculate/generator/amount"] is ImpactClassification.DIRECT
    assert by_path["scenario:/step/calculate/derive/next"] is ImpactClassification.TRANSITIVE_POSSIBLE
    assert by_path["scenario:/step/calculate/write/total"] is ImpactClassification.TRANSITIVE_POSSIBLE
    assert by_path["scenario:/state/total"] is ImpactClassification.TRANSITIVE_POSSIBLE
    assert by_path["scenario:/invariant/total_valid"] is ImpactClassification.TRANSITIVE_POSSIBLE
    assert by_path["scenario:/step/calculate/emit/emissions"] is ImpactClassification.TRANSITIVE_POSSIBLE
    value = result.to_jsonable()
    assert value["schema"] == "scenario.impact/1"
    assert value["definition_diff"]["contract"] == "scenario.definition-diff/1"
    assert value["claims"] == {"behavioral_equivalence": False, "complete_impact_proof": False,
                               "unknown_means_unaffected": False}


def test_zero_change_is_successful_and_has_no_fake_unknown() -> None:
    document = parse_yaml(BASE)
    value = analyze_impact(document, parse_yaml("\n# formatting only\n" + BASE)).to_jsonable()
    assert value["summary"] == {"impacted_entity_count": 0,
                                "counts": {"DIRECT": 0, "TRANSITIVE_POSSIBLE": 0, "UNKNOWN": 0}}
    assert value["amplification"]["numerator"] == 0
    assert value["amplification"]["reduced_fraction"] == "0/1"


def test_removed_writer_uses_before_graph_and_cycles_are_bounded() -> None:
    left = BASE.replace("    transition: finish\n  - id: finish",
                        "    transition: mirror\n  - id: mirror\n    derive: {again: {$state: total}}\n    write: {total: {$derived: again}}\n    transition: finish\n  - id: finish")
    result = analyze_impact(parse_yaml(left), parse_yaml(BASE))
    removed = [record for record in result.records if record.source_change.semantic_path == "scenario:/step/mirror"]
    assert removed and any(record.affected_semantic_path == "scenario:/state/total" for record in removed)
    assert len({(record.source_change.semantic_path, record.affected_semantic_path) for record in result.records}) == len(result.records)


def test_plugin_argument_uncertainty_is_explicit_unknown() -> None:
    plugin = BASE.replace("generate: {amount: {$int: [1, 2]}}",
                          "generate:\n      amount: {$plugin: {name: custom, version: '1', args: {maximum: {$resource: limit}}}}")
    changed = plugin.replace("{$literal: 10}", "{$literal: 11}")
    records = {record.affected_semantic_path: record for record in analyze_impact(parse_yaml(plugin), parse_yaml(changed)).records}
    assert records["scenario:/resource/limit"].classification is ImpactClassification.DIRECT
    assert records["scenario:/step/calculate/generator/amount"].classification is ImpactClassification.UNKNOWN
    assert records["scenario:/step/calculate/derive/next"].classification is ImpactClassification.UNKNOWN


def test_cli_is_deterministic_validates_both_inputs_and_has_clear_help(tmp_path: Path) -> None:
    left = tmp_path / "left.yaml"; right = tmp_path / "right.yaml"
    left.write_text(BASE, encoding="utf-8")
    right.write_text(BASE.replace("{$int: [1, 2]}", "{$int: [1, 3]}"), encoding="utf-8")
    first = invoke("--json", "impact", str(left), str(right)); second = invoke("--json", "impact", str(left), str(right))
    assert first.returncode == second.returncode == CLIExitCode.SUCCESS
    assert first.stdout == second.stdout and first.stderr == second.stderr == b""
    assert json.loads(first.stdout)["schema"] == "scenario.impact/1"
    human = invoke("impact", str(left), str(right))
    assert human.returncode == 0 and b"no behavioral equivalence or complete impact proof is claimed" in human.stdout
    help_result = invoke("impact", "--help")
    assert help_result.returncode == 0 and b"UNKNOWN != UNAFFECTED" in help_result.stdout
    invalid = tmp_path / "invalid.yaml"; invalid.write_text("dsl_version: 1\n", encoding="utf-8")
    failure = invoke("--json", "impact", str(left), str(invalid))
    assert failure.returncode == CLIExitCode.VALIDATION and failure.stdout == b""
    assert json.loads(failure.stderr)["schema"] == "scenario.error/1"
