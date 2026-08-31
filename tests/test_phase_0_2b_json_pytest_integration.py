from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import tomllib
import unittest

from scenario_engine.adapters import write_result_json
from scenario_engine.pytest_plugin import ScenarioHarness
from scenario_engine.result import ScenarioResult


ROOT = Path(__file__).parents[1]
SRC = ROOT / "src"
AUDIT_PYTHON = Path(
    "/Users/smshahinulislam/Developer/scenario-engine-audit/runtime-venv/bin/python"
)
SCENARIO = """
dsl_version: 1
scenario: phase02b
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
    advance: {seconds: 2}
    transition: null
"""


def run_result(seed: str = "seed", run_index: int = 0) -> ScenarioResult:
    return ScenarioHarness().run_text(
        SCENARIO, root_seed=seed, run_index=run_index, locale="C",
    )


def subprocess_environment() -> dict[str, str]:
    environment = os.environ.copy()
    existing = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = str(SRC) + (os.pathsep + existing if existing else "")
    return environment


class Phase02BJsonPytestIntegrationTests(unittest.TestCase):
    def test_json_adapter_writes_exact_stable_result_bytes(self):
        result = run_result()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "result.json"
            write_result_json(result, target)
            self.assertEqual(target.read_bytes(), result.to_json_bytes())

    def test_json_adapter_repeated_outputs_are_byte_identical(self):
        first = run_result()
        second = run_result()
        with tempfile.TemporaryDirectory() as directory:
            one, two = Path(directory) / "one.json", Path(directory) / "two.json"
            write_result_json(first, one)
            write_result_json(second, two)
            self.assertEqual(one.read_bytes(), two.read_bytes())

    def test_json_adapter_refuses_existing_target_by_default(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "result.json"
            target.write_bytes(b"sentinel")
            with self.assertRaises(FileExistsError):
                write_result_json(run_result(), target)
            self.assertEqual(target.read_bytes(), b"sentinel")

    def test_json_adapter_overwrite_replaces_with_exact_result(self):
        result = run_result()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "result.json"
            target.write_bytes(b"old")
            write_result_json(result, target, overwrite=True)
            self.assertEqual(target.read_bytes(), result.to_json_bytes())

    def test_json_adapter_requires_existing_parent_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "missing" / "result.json"
            with self.assertRaises(FileNotFoundError):
                write_result_json(run_result(), target)
            self.assertFalse(target.parent.exists())

    def test_json_adapter_preserves_typed_semantics_on_disk(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "result.json"
            write_result_json(run_result(), target)
            payload = json.loads(target.read_bytes())
        state = payload["state"]
        self.assertEqual(state["money"], {"$type": "decimal", "value": "10.50"})
        self.assertEqual(state["missing"], {"$type": "missing"})
        self.assertIsNone(state["nothing"])
        self.assertEqual(state["entity_id"]["$type"], "logical-id")
        self.assertEqual(payload["clock"]["$type"], "datetime")

    def test_scenario_harness_run_text_returns_scenario_result(self):
        result = ScenarioHarness().run_text(SCENARIO, root_seed="harness", run_index=3)
        self.assertIsInstance(result, ScenarioResult)
        self.assertEqual(result.manifest.run_index, 3)
        self.assertTrue(result.manifest.scenario_canonical_hash)

    def test_scenario_harness_run_file_returns_scenario_result(self):
        harness = ScenarioHarness()
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "scenario.yaml"
            source.write_text(SCENARIO, encoding="utf-8")
            from_file = harness.run_file(source, root_seed="file", run_index=2)
        from_text = harness.run_text(SCENARIO, root_seed="file", run_index=2)
        self.assertIsInstance(from_file, ScenarioResult)
        self.assertEqual(from_file.normalized(), from_text.normalized())

    def test_scenario_harness_replay_text_is_exact(self):
        harness = ScenarioHarness()
        original = harness.run_text(SCENARIO, root_seed="replay", run_index=5)
        replayed = harness.replay_text(SCENARIO, original.manifest)
        self.assertEqual(replayed.normalized(), original.normalized())

    def test_scenario_harness_replay_file_is_exact(self):
        harness = ScenarioHarness()
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "scenario.yaml"
            source.write_text(SCENARIO, encoding="utf-8")
            original = harness.run_file(source, root_seed="replay-file", run_index=6)
            replayed = harness.replay_file(source, original.manifest)
        self.assertEqual(replayed.normalized(), original.normalized())

    def test_scenario_harness_same_context_replays_deterministically(self):
        harness = ScenarioHarness()
        first = harness.run_text(SCENARIO, root_seed="same", run_index=7, locale="C")
        second = harness.run_text(SCENARIO, root_seed="same", run_index=7, locale="C")
        self.assertEqual(first.normalized(), second.normalized())
        self.assertEqual(first.to_json_bytes(), second.to_json_bytes())

    def test_core_package_does_not_import_pytest_plugin(self):
        code = textwrap.dedent("""
            import sys
            import scenario_engine
            assert 'scenario_engine.pytest_plugin' not in sys.modules
            print('isolated-core-import-pass')
        """)
        completed = subprocess.run(
            [sys.executable, "-I", "-c", f"import sys; sys.path.insert(0, {str(SRC)!r});\n{code}"],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_pyproject_declares_optional_pytest_integration_without_core_runtime_dependency(self):
        document = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(document["project"]["dependencies"], ["PyYAML==6.0.3"])
        self.assertEqual(document["project"]["optional-dependencies"]["pytest"],
                         ["pytest>=9.1,<10"])
        self.assertEqual(document["project"]["entry-points"]["pytest11"]["scenario_engine"],
                         "scenario_engine.pytest_plugin")

    def test_real_pytest_process_loads_scenario_engine_fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            test_file = Path(directory) / "test_fixture.py"
            test_file.write_text(textwrap.dedent(f'''\
                pytest_plugins = ["scenario_engine.pytest_plugin"]
                from scenario_engine.result import ScenarioResult
                SCENARIO = {SCENARIO!r}
                def test_fixture(scenario_engine):
                    first = scenario_engine.run_text(SCENARIO, root_seed="pytest", run_index=4)
                    second = scenario_engine.run_text(SCENARIO, root_seed="pytest", run_index=4)
                    assert isinstance(first, ScenarioResult)
                    assert first.normalized() == second.normalized()
                    assert first.manifest.run_index == 4
            '''), encoding="utf-8")
            completed = subprocess.run(
                [str(AUDIT_PYTHON), "-m", "pytest", "-q", str(test_file)],
                cwd=directory, env=subprocess_environment(), capture_output=True, text=True,
            )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_real_pytest_process_runs_scenario_from_file(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "scenario.yaml"
            source.write_text(SCENARIO, encoding="utf-8")
            test_file = Path(directory) / "test_file_fixture.py"
            test_file.write_text(textwrap.dedent(f'''\
                pytest_plugins = ["scenario_engine.pytest_plugin"]
                from pathlib import Path
                from scenario_engine.result import ScenarioResult
                def test_file_fixture(scenario_engine):
                    result = scenario_engine.run_file(Path({str(source)!r}), root_seed="pytest-file", run_index=8)
                    assert isinstance(result, ScenarioResult)
                    assert result.manifest.run_index == 8
                    assert result.final_state["money"].as_tuple().exponent == -2
            '''), encoding="utf-8")
            completed = subprocess.run(
                [str(AUDIT_PYTHON), "-m", "pytest", "-q", str(test_file)],
                cwd=directory, env=subprocess_environment(), capture_output=True, text=True,
            )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_pytest_harness_and_json_adapter_compose(self):
        result = ScenarioHarness().run_text(SCENARIO, root_seed="compose", run_index=9)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "result.json"
            write_result_json(result, target)
            self.assertEqual(target.read_bytes(), result.to_json_bytes())


if __name__ == "__main__":
    unittest.main()
