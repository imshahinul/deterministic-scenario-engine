from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from scenario_engine.address import ExecutionAddress
from scenario_engine.clock import LogicalClock
from scenario_engine.runner import ScenarioRunner
from scenario_engine.state import ScenarioState
from scenario_engine.values import normalize

from .errors import DSLCompilationError
from .models import CompiledScenario


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    runner: ScenarioRunner

    def normalized(self) -> Any:
        subject = self.runner
        return normalize({
            "state": subject.state.to_dict(),
            "history": [{
                "address": record.address.canonical(),
                "timestamp": record.logical_timestamp,
                "pre": record.pre_state_fingerprint,
                "patch": record.state_patch,
                "post": record.post_state_fingerprint,
                "artifacts": [[item_id, kind] for item_id, kind in record.emitted_artifacts],
                "transition": record.transition_selected,
            } for record in subject.history.records],
            "artifacts": [{
                "type": artifact.artifact_type,
                "name": artifact.name,
                "value": artifact.value,
                "id": artifact.logical_id,
                "address": artifact.address.canonical(),
            } for artifact in subject.artifacts],
            "clock": subject.clock.current,
            "next": subject.next_step,
        })


def run_scenario(scenario: CompiledScenario, root_seed: str | int, run_index: int = 0) -> ScenarioResult:
    if isinstance(run_index, bool) or not isinstance(run_index, int) or run_index < 0:
        raise ValueError("run_index must be a nonnegative integer")
    runner = ScenarioRunner(
        root_seed,
        ExecutionAddress(scenario.scenario_id, run_index),
        ScenarioState(scenario.initial_state),
        LogicalClock(scenario.reference_clock_start),
    )
    by_id = {step.step_id: step for step in scenario.steps}
    current: str | None = scenario.start_step
    executed = 0
    while current is not None:
        if executed >= len(scenario.steps):
            raise DSLCompilationError("defensive execution bound exceeded")
        try:
            step = by_id[current]
        except KeyError:
            raise DSLCompilationError(f"runtime transition targets unknown step {current}") from None
        candidate = runner.run_step(step.spec)
        current = candidate.transition
        executed += 1
    return ScenarioResult(runner)
