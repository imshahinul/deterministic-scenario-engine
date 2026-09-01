"""Hypothesis composition at the deterministic engine's explicit boundary."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

try:
    from hypothesis import strategies as st
    from hypothesis.strategies import SearchStrategy
except ImportError as error:  # pragma: no cover - exercised in dependency-isolation subprocesses
    raise ImportError(
        "scenario_engine.integrations.hypothesis requires the optional "
        "'hypothesis' extra (hypothesis>=6,<7)"
    ) from error

from scenario_engine.dsl.compiler import compile_document
from scenario_engine.dsl.parser import parse_yaml
from scenario_engine.dsl.runtime import run_scenario
from scenario_engine.plugins import PluginRegistry
from scenario_engine.result import ScenarioResult


class HypothesisIntegrationError(ValueError):
    """The explicit property-testing adapter contract is invalid."""


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(value[key]) for key in sorted(value)})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return deepcopy(value)


@dataclass(frozen=True, slots=True)
class ScenarioHypothesisCase:
    """A drawn, explicit and independently replayable scenario execution."""

    yaml_text: str
    root_seed: Any
    run_index: int
    inputs: Mapping[str, Any]
    locale: str
    plugins: PluginRegistry | None
    result: ScenarioResult


def scenario_cases(
    yaml_text: str,
    *,
    root_seed: Any,
    run_indexes: SearchStrategy[int] | None = None,
    inputs: SearchStrategy[Mapping[str, Any]] | None = None,
    plugins: PluginRegistry | None = None,
    locale: str = "C",
) -> SearchStrategy[ScenarioHypothesisCase]:
    """Draw explicit inputs/run indexes, then execute the normal engine API."""
    if not isinstance(yaml_text, str):
        raise HypothesisIntegrationError("yaml_text must be a string")
    run_indexes = st.integers(min_value=0, max_value=1000) if run_indexes is None else run_indexes
    inputs = st.just({}) if inputs is None else inputs
    if not isinstance(run_indexes, SearchStrategy) or not isinstance(inputs, SearchStrategy):
        raise HypothesisIntegrationError("run_indexes and inputs must be Hypothesis strategies")

    @st.composite
    def explicit_cases(draw: Any) -> ScenarioHypothesisCase:
        run_index = draw(run_indexes)
        drawn_inputs = draw(inputs)
        if not isinstance(drawn_inputs, Mapping) or not all(isinstance(key, str) for key in drawn_inputs):
            raise HypothesisIntegrationError("drawn inputs must be a string-keyed mapping")
        execution_inputs = deepcopy(dict(drawn_inputs))
        scenario = compile_document(parse_yaml(yaml_text))
        result = run_scenario(
            scenario,
            root_seed,
            run_index,
            locale=locale,
            inputs=deepcopy(execution_inputs),
            plugins=plugins,
        )
        return ScenarioHypothesisCase(
            yaml_text=yaml_text,
            root_seed=deepcopy(root_seed),
            run_index=run_index,
            inputs=_freeze(execution_inputs),
            locale=locale,
            plugins=plugins,
            result=result,
        )

    return explicit_cases()


__all__ = [
    "HypothesisIntegrationError",
    "ScenarioHypothesisCase",
    "scenario_cases",
]
