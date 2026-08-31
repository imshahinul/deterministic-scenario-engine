"""Optional pytest integration for deterministic scenario execution."""

from __future__ import annotations

from pathlib import Path

import pytest

from scenario_engine.dsl import compile_document, evaluate_scenario, parse_yaml, replay_scenario, run_scenario
from scenario_engine.manifest import ReproducibilityManifest
from scenario_engine.result import ScenarioResult


class ScenarioHarness:
    """Ergonomic glue over the frozen DSL runtime and exact replay APIs."""

    def run_text(
        self,
        yaml_text: str,
        *,
        root_seed: str | int,
        run_index: int = 0,
        locale: str = "C",
        inputs=None,
    ) -> ScenarioResult:
        scenario = compile_document(parse_yaml(yaml_text))
        return run_scenario(scenario, root_seed, run_index, locale, inputs)

    def run_file(
        self,
        path: str | Path,
        *,
        root_seed: str | int,
        run_index: int = 0,
        locale: str = "C",
        inputs=None,
    ) -> ScenarioResult:
        return self.run_text(
            Path(path).read_text(encoding="utf-8"),
            root_seed=root_seed,
            run_index=run_index,
            locale=locale,
            inputs=inputs,
        )

    def replay_text(
        self,
        yaml_text: str,
        manifest: ReproducibilityManifest,
        *,
        inputs=None,
    ) -> ScenarioResult:
        return replay_scenario(yaml_text, manifest, inputs=inputs)

    def replay_file(
        self,
        path: str | Path,
        manifest: ReproducibilityManifest,
        *,
        inputs=None,
    ) -> ScenarioResult:
        return self.replay_text(Path(path).read_text(encoding="utf-8"), manifest, inputs=inputs)

    def evaluate_text(self, yaml_text: str, *, root_seed: str | int, run_index: int = 0,
                      locale: str = "C", inputs=None, raise_on_mismatch: bool = False):
        return evaluate_scenario(compile_document(parse_yaml(yaml_text)), root_seed, run_index,
                                 locale, inputs, raise_on_mismatch)

    def evaluate_file(self, path: str | Path, *, root_seed: str | int, run_index: int = 0,
                      locale: str = "C", inputs=None, raise_on_mismatch: bool = False):
        return self.evaluate_text(Path(path).read_text(encoding="utf-8"), root_seed=root_seed,
            run_index=run_index, locale=locale, inputs=inputs, raise_on_mismatch=raise_on_mismatch)


@pytest.fixture
def scenario_engine() -> ScenarioHarness:
    """Provide an isolated deterministic scenario harness."""
    return ScenarioHarness()
