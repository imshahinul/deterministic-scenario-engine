"""Optional pytest integration for deterministic scenario execution."""

from __future__ import annotations

from pathlib import Path

from scenario_engine.errors import PytestIntegrationError

try:
    import pytest
except ModuleNotFoundError as error:
    if error.name != "pytest":
        raise
    raise PytestIntegrationError(
        "pytest integration requires the optional 'pytest' extra"
    ) from None

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
        plugins=None,
    ) -> ScenarioResult:
        scenario = compile_document(parse_yaml(yaml_text))
        return run_scenario(scenario, root_seed, run_index, locale, inputs, plugins)

    def run_file(
        self,
        path: str | Path,
        *,
        root_seed: str | int,
        run_index: int = 0,
        locale: str = "C",
        inputs=None,
        plugins=None,
    ) -> ScenarioResult:
        return self.run_text(
            Path(path).read_text(encoding="utf-8"),
            root_seed=root_seed,
            run_index=run_index,
            locale=locale,
            inputs=inputs,
            plugins=plugins,
        )

    def replay_text(
        self,
        yaml_text: str,
        manifest: ReproducibilityManifest,
        *,
        inputs=None,
        plugins=None,
    ) -> ScenarioResult:
        return replay_scenario(yaml_text, manifest, inputs=inputs, plugins=plugins)

    def replay_file(
        self,
        path: str | Path,
        manifest: ReproducibilityManifest,
        *,
        inputs=None,
        plugins=None,
    ) -> ScenarioResult:
        return self.replay_text(Path(path).read_text(encoding="utf-8"), manifest, inputs=inputs, plugins=plugins)

    def evaluate_text(self, yaml_text: str, *, root_seed: str | int, run_index: int = 0,
                      locale: str = "C", inputs=None, raise_on_mismatch: bool = False,
                      plugins=None):
        return evaluate_scenario(compile_document(parse_yaml(yaml_text)), root_seed, run_index,
                                 locale, inputs, raise_on_mismatch, plugins)

    def evaluate_file(self, path: str | Path, *, root_seed: str | int, run_index: int = 0,
                      locale: str = "C", inputs=None, raise_on_mismatch: bool = False,
                      plugins=None):
        return self.evaluate_text(Path(path).read_text(encoding="utf-8"), root_seed=root_seed,
            run_index=run_index, locale=locale, inputs=inputs,
            raise_on_mismatch=raise_on_mismatch, plugins=plugins)


@pytest.fixture
def scenario_engine() -> ScenarioHarness:
    """Provide an isolated deterministic scenario harness."""
    return ScenarioHarness()
