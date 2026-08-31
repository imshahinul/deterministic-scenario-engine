from __future__ import annotations

from dataclasses import fields, replace
import json
from pathlib import Path
import unittest

from scenario_engine.canonical import canonical_scenario_hash
from scenario_engine.dsl import compile_document, parse_yaml, replay_scenario, run_scenario
from scenario_engine.ids import ID_VERSION
from scenario_engine.manifest import (
    ENGINE_VERSION, GENERATOR_VERSIONS, ReplayCompatibilityError,
)
from scenario_engine.rng import RNG_VERSION


EXAMPLE = Path(__file__).parents[1] / "examples" / "phase0_1b_cart.yaml"
BASE = """
dsl_version: 1
scenario: phase02a
clock: {start: '2026-01-01T12:00:00+00:00'}
initial_state:
  money: {$decimal: '10.50'}
  missing: {$missing: true}
  nothing: null
steps:
  - id: create
    generate:
      identity: {$id: entity}
      number: {$int: [1, 20]}
    write:
      entity_id: {$local: identity}
      number: {$local: number}
    emit:
      - type: first
        fields: {value: {$state: money}}
      - type: second
        fields: {value: {$state: nothing}}
    advance: {seconds: 2}
    transition: finish
  - id: finish
    write:
      finished: {$literal: true}
    advance: {seconds: 3}
    transition: null
"""


def compiled(text: str = BASE):
    return compile_document(parse_yaml(text))


class ReproducibleResultTests(unittest.TestCase):
    def test_canonical_hash_ignores_comments_whitespace_and_mapping_order(self):
        reordered = BASE.replace(
            "dsl_version: 1\nscenario: phase02a\nclock: {start: '2026-01-01T12:00:00+00:00'}",
            "# equivalent document\nclock:\n  start: '2026-01-01T12:00:00+00:00'\nscenario: phase02a\ndsl_version: 1",
        ).replace(
            "      identity: {$id: entity}\n      number: {$int: [1, 20]}",
            "      number: { $int: [1, 20] }\n      identity: { $id: entity }",
        )
        self.assertEqual(canonical_scenario_hash(BASE), canonical_scenario_hash(reordered))

    def test_canonical_hash_preserves_semantically_significant_list_order(self):
        swapped = BASE.replace(
            "      - type: first\n        fields: {value: {$state: money}}\n      - type: second\n        fields: {value: {$state: nothing}}",
            "      - type: second\n        fields: {value: {$state: nothing}}\n      - type: first\n        fields: {value: {$state: money}}",
        )
        self.assertNotEqual(canonical_scenario_hash(BASE), canonical_scenario_hash(swapped))

    def test_canonical_hash_changes_on_semantic_change(self):
        changed = BASE.replace("{$decimal: '10.50'}", "{$decimal: '10.51'}")
        self.assertNotEqual(canonical_scenario_hash(BASE), canonical_scenario_hash(changed))

    def test_manifest_contains_complete_phase0_2a_contract(self):
        manifest = run_scenario(compiled(), "seed", 4).manifest
        self.assertEqual(
            {item.name for item in fields(manifest)},
            {"root_seed", "scenario_canonical_hash", "engine_version", "dsl_version",
             "input_resource_hashes", "domain_pack_versions", "generator_versions",
             "rng_algorithm_version", "id_algorithm_version", "locale",
             "reference_clock_start", "run_index"},
        )
        self.assertEqual(dict(manifest.input_resource_hashes), {})
        self.assertEqual(dict(manifest.domain_pack_versions), {})

    def test_manifest_uses_explicit_engine_and_algorithm_versions(self):
        manifest = run_scenario(compiled(), "seed").manifest
        self.assertEqual(ENGINE_VERSION, "0.2.0.dev0")
        self.assertEqual(manifest.rng_algorithm_version, RNG_VERSION)
        self.assertEqual(manifest.id_algorithm_version, ID_VERSION)
        self.assertEqual(dict(manifest.generator_versions), dict(GENERATOR_VERSIONS))

    def test_same_context_produces_identical_manifest_and_result(self):
        first = run_scenario(compiled(), 42, 8, locale="C")
        second = run_scenario(compiled(), 42, 8, locale="C")
        self.assertEqual(first.manifest, second.manifest)
        self.assertEqual(first.normalized(), second.normalized())
        self.assertEqual(first.to_json(), second.to_json())

    def test_different_run_index_is_recorded_and_independently_addressed(self):
        first = run_scenario(compiled(), "seed", 1)
        second = run_scenario(compiled(), "seed", 2)
        self.assertEqual(first.manifest.run_index, 1)
        self.assertEqual(second.manifest.run_index, 2)
        self.assertNotEqual(first.history.records[0].address, second.history.records[0].address)
        self.assertEqual(replay_scenario(BASE, first.manifest).normalized(), first.normalized())

    def test_scenario_result_normalization_is_stable(self):
        result = run_scenario(compiled(), "seed")
        first = result.normalized()
        first["state"]["number"] = -1
        self.assertEqual(result.normalized(), result.normalized())
        self.assertNotEqual(first, result.normalized())

    def test_result_json_is_byte_stable(self):
        result = run_scenario(compiled(), "seed")
        self.assertEqual(result.to_json(), result.to_json())
        self.assertEqual(result.to_json_bytes(), result.to_json().encode("utf-8"))

    def test_result_json_preserves_decimal_datetime_id_missing_and_null_semantics(self):
        payload = json.loads(run_scenario(compiled(), "seed").to_json())
        state = payload["state"]
        self.assertEqual(state["money"]["$type"], "decimal")
        self.assertEqual(state["missing"], {"$type": "missing"})
        self.assertIsNone(state["nothing"])
        self.assertEqual(state["entity_id"]["$type"], "logical-id")
        self.assertEqual(payload["clock"]["$type"], "datetime")

    def test_result_json_does_not_convert_decimal_money_to_float(self):
        money = json.loads(run_scenario(compiled(), "seed").to_json())["state"]["money"]
        self.assertEqual(money, {"$type": "decimal", "value": "10.50"})
        self.assertNotIsInstance(money["value"], float)

    def test_exact_replay_from_matching_manifest_succeeds(self):
        original = run_scenario(compiled(), "replay", 9)
        replayed = replay_scenario(BASE, original.manifest)
        self.assertEqual(replayed.normalized(), original.normalized())

    def test_replay_rejects_scenario_hash_mismatch(self):
        manifest = run_scenario(compiled(), "seed").manifest
        with self.assertRaisesRegex(ReplayCompatibilityError, "scenario_canonical_hash"):
            replay_scenario(BASE.replace("10.50", "10.51"), manifest)

    def test_replay_rejects_engine_or_algorithm_version_mismatch(self):
        manifest = run_scenario(compiled(), "seed").manifest
        with self.assertRaisesRegex(ReplayCompatibilityError, "engine_version"):
            replay_scenario(BASE, replace(manifest, engine_version="future"))
        with self.assertRaisesRegex(ReplayCompatibilityError, "rng_algorithm_version"):
            replay_scenario(BASE, replace(manifest, rng_algorithm_version="future"))

    def test_replay_rejects_unsupported_resource_or_domain_manifest_state(self):
        manifest = run_scenario(compiled(), "seed").manifest
        with self.assertRaisesRegex(ReplayCompatibilityError, "input_resource_hashes"):
            replay_scenario(BASE, replace(manifest, input_resource_hashes={"a": "sha256:x"}))
        with self.assertRaisesRegex(ReplayCompatibilityError, "domain_pack_versions"):
            replay_scenario(BASE, replace(manifest, domain_pack_versions={"a": "1"}))

    def test_trace_is_deterministic_and_commit_ordered(self):
        result = run_scenario(compiled(), "seed", 3)
        before = result.history.records
        first, second = result.trace(), result.trace()
        self.assertEqual(first, second)
        self.assertEqual(result.history.records, before)
        self.assertEqual([json.loads(row["address"])["step"] for row in first],
                         ["create", "finish"])
        self.assertEqual([row["transition"] for row in first], ["finish", None])
        self.assertTrue(all({"address", "timestamp", "pre", "patch", "post",
                             "artifacts", "transition", "faults_applied"} <= set(row)
                            for row in first))

    def test_equivalent_yaml_key_order_has_same_hash_and_result(self):
        reordered = BASE.replace(
            "      entity_id: {$local: identity}\n      number: {$local: number}",
            "      number: {$local: number}\n      entity_id: {$local: identity}",
        )
        first = run_scenario(compiled(BASE), "seed")
        second = run_scenario(compiled(reordered), "seed")
        self.assertEqual(first.manifest.scenario_canonical_hash,
                         second.manifest.scenario_canonical_hash)
        self.assertEqual(first.normalized(), second.normalized())

    def test_phase0_1_example_runs_under_result_manifest_contract(self):
        source = EXAMPLE.read_text(encoding="utf-8")
        result = run_scenario(compiled(source), "example", 2)
        self.assertEqual(result.manifest.dsl_version, 1)
        self.assertEqual(len(result.history.records), 3)
        self.assertEqual(result.to_json(), result.to_json())
        self.assertEqual(replay_scenario(source, result.manifest).normalized(), result.normalized())


if __name__ == "__main__":
    unittest.main()
