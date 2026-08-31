from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Any, Mapping

from scenario_engine.runner import StepSpec


def frozen_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(dict(value))


@dataclass(frozen=True, slots=True)
class StepDocument:
    step_id: str
    generate: Mapping[str, Any]
    derive: Mapping[str, Any]
    write: Mapping[str, Any]
    emit: tuple[Mapping[str, Any], ...]
    advance: timedelta
    transition: str | None


@dataclass(frozen=True, slots=True)
class ScenarioDocument:
    dsl_version: int
    scenario_id: str
    reference_clock_start: datetime
    initial_state: Mapping[str, Any]
    steps: tuple[StepDocument, ...]


@dataclass(frozen=True, slots=True)
class CompiledStep:
    spec: StepSpec
    transition: str | None

    @property
    def step_id(self) -> str:
        return self.spec.step_id


@dataclass(frozen=True, slots=True)
class CompiledScenario:
    scenario_id: str
    reference_clock_start: datetime
    initial_state: Mapping[str, Any]
    steps: tuple[CompiledStep, ...]
    start_step: str
