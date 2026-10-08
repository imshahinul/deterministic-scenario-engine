from __future__ import annotations

from dataclasses import dataclass, field
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
    call: Mapping[str, Any] | None = None
    branch: Mapping[str, Any] | None = None
    repeat: Mapping[str, Any] | None = None

    @property
    def control_kind(self) -> str | None:
        if self.call is not None:
            return "call"
        if self.branch is not None:
            return "branch"
        if self.repeat is not None:
            return "repeat"
        return None


@dataclass(frozen=True, slots=True)
class ScenarioDocument:
    dsl_version: int
    scenario_id: str
    reference_clock_start: datetime
    initial_state: Mapping[str, Any]
    steps: tuple[StepDocument, ...]
    resources: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    validators: tuple[Mapping[str, Any], ...] = ()
    constraints: tuple[Mapping[str, Any], ...] = ()
    subflows: Mapping[str, tuple[StepDocument, ...]] = field(default_factory=lambda: MappingProxyType({}))
    invariants: tuple[Mapping[str, Any], ...] = ()
    faults: tuple[Mapping[str, Any], ...] = ()
    oracle: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class ActorDocument:
    actor_id: str
    address: str
    steps: tuple[StepDocument, ...]
    subflows: Mapping[str, tuple[StepDocument, ...]] = field(
        default_factory=lambda: MappingProxyType({})
    )


@dataclass(frozen=True, slots=True)
class ScenarioDocumentV2:
    """Validated immutable DSL 2 actor declarations; not an execution model."""

    dsl_version: int
    scenario_id: str
    reference_clock_start: datetime
    initial_state: Mapping[str, Any]
    actors: tuple[ActorDocument, ...]
    resources: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    validators: tuple[Mapping[str, Any], ...] = ()
    constraints: tuple[Mapping[str, Any], ...] = ()
    invariants: tuple[Mapping[str, Any], ...] = ()
    oracle: Mapping[str, Any] | None = None


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
    document: ScenarioDocument
    resources: Any = None
    subflows: Mapping[str, tuple[CompiledStep | StepDocument, ...]] = field(default_factory=lambda: MappingProxyType({}))


@dataclass(frozen=True, slots=True)
class CompiledScenarioV2:
    """Statically validated DSL 2 foundation with no executable scheduler state."""

    scenario_id: str
    reference_clock_start: datetime
    initial_state: Mapping[str, Any]
    actors: tuple[ActorDocument, ...]
    document: ScenarioDocumentV2
    resources: Any = None
