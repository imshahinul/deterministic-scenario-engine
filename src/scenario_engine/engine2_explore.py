"""Finite explicit schedule-seed sweeps over the Engine 2 suite runner.

This module derives a convenience summary from authoritative Engine2SuiteOutcome
evidence.  It does not define a new canonical evidence contract or perform
systematic scheduler exploration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .dsl.models import CompiledScenarioV2
from .engine2_suite import (
    MAX_SUITE_CASES,
    Engine2CaseRequest,
    Engine2SuiteBoundError,
    Engine2SuiteError,
    Engine2SuiteOutcome,
    Engine2SuitePlan,
    execute_engine2_suite,
)
from .plugins import PluginRegistry
from .scheduler import MAX_SCHEDULE_SEED


CASE_ID_FORMAT = "seed-sweep-{position:02d}"
_SEED_SWEEP_VARYING_REQUEST_FIELDS = frozenset({"case_id", "position", "schedule_seed"})


@dataclass(frozen=True, slots=True)
class Engine2SeedSweepRequest:
    """One bounded ordered seed sweep, fully validated before execution."""

    scenario: CompiledScenarioV2 = field(repr=False)
    root_seed: str | int
    schedule_seeds: list[int] | tuple[int, ...]
    run_index: int
    inputs: Mapping[str, Any] | None = field(default=None, repr=False, compare=False)
    plugins: PluginRegistry | None = field(default=None, repr=False, compare=False)
    expected_classification: str = "SUCCESS"
    expected_failure_code: str | None = None
    _cases: tuple[Engine2CaseRequest, ...] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        # Exact concrete types reject sets, mappings, strings, and generators
        # without iterating or materializing them.
        if type(self.schedule_seeds) not in (list, tuple):
            raise Engine2SuiteError("schedule_seeds", "must be an explicit ordered list or tuple")
        seeds = tuple(self.schedule_seeds)
        if not 1 <= len(seeds) <= MAX_SUITE_CASES:
            raise Engine2SuiteBoundError(
                "schedule_seeds", f"must contain 1..{MAX_SUITE_CASES} seeds",
            )
        for index, seed in enumerate(seeds):
            if isinstance(seed, bool) or not isinstance(seed, int):
                raise Engine2SuiteError(
                    f"schedule_seeds[{index}]", "must be an integer excluding bool",
                )
            if seed < 0:
                raise Engine2SuiteError(
                    f"schedule_seeds[{index}]",
                    f"must be in the inclusive range 0..{MAX_SCHEDULE_SEED}",
                )
            if seed > MAX_SCHEDULE_SEED:
                raise Engine2SuiteBoundError(
                    f"schedule_seeds[{index}]",
                    f"must be in the inclusive range 0..{MAX_SCHEDULE_SEED}",
                )
        if len(seeds) != len(set(seeds)):
            raise Engine2SuiteError("schedule_seeds", "must not contain duplicate seeds")

        # Engine2CaseRequest remains the single validator for all common native,
        # compatibility, resource, input, plugin, and expectation coordinates.
        cases = tuple(
            Engine2CaseRequest(
                CASE_ID_FORMAT.format(position=position),
                self.scenario,
                self.root_seed,
                seed,
                run_index=self.run_index,
                inputs=self.inputs,
                plugins=self.plugins,
                expected_classification=self.expected_classification,
                expected_failure_code=self.expected_failure_code,
                position=position,
            )
            for position, seed in enumerate(seeds)
        )
        object.__setattr__(self, "schedule_seeds", seeds)
        # Retain the first request's immutable input representation so caller
        # mutations after validation cannot affect later plan construction.
        object.__setattr__(self, "inputs", cases[0].inputs)
        object.__setattr__(self, "_cases", cases)


@dataclass(frozen=True, slots=True)
class Engine2SeedSweepFailure:
    """One non-success suite status and its exact seed coordinate."""

    case_id: str
    case_identity: str
    position: int
    schedule_seed: int
    status: str


@dataclass(frozen=True, slots=True)
class Engine2SeedSweepOutcome:
    """Immutable suite-derived view; ``suite`` remains authoritative evidence."""

    suite: Engine2SuiteOutcome
    schedule_seeds: tuple[int, ...] = field(init=False)
    case_ids: tuple[str, ...] = field(init=False)
    case_identities: tuple[str, ...] = field(init=False)
    plan_identity: str = field(init=False)
    attempted_cases: int = field(init=False)
    success_count: int = field(init=False)
    expected_failure_count: int = field(init=False)
    unexpected_failure_count: int = field(init=False)
    error_count: int = field(init=False)
    failing_cases: tuple[Engine2SeedSweepFailure, ...] = field(init=False)
    schedule_artifact_identities: tuple[str, ...] = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.suite, Engine2SuiteOutcome):
            raise TypeError("suite must be Engine2SuiteOutcome")
        cases = self.suite.cases
        first_request = cases[0].request
        common_coordinates = {
            name: value for name, value in first_request.items()
            if name not in _SEED_SWEEP_VARYING_REQUEST_FIELDS
        }
        seen_seeds: set[int] = set()
        for position, item in enumerate(cases):
            request = item.request
            if request["position"] != position:
                raise Engine2SuiteError(
                    "suite", "seed-sweep positions must equal ordered case indexes",
                )
            if request["case_id"] != CASE_ID_FORMAT.format(position=position):
                raise Engine2SuiteError(
                    "suite", "case IDs must use the ordered seed-sweep format",
                )
            seed = request["schedule_seed"]
            if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= MAX_SCHEDULE_SEED:
                raise Engine2SuiteError(
                    "suite", "schedule seeds must be native-range integers excluding bool",
                )
            if seed in seen_seeds:
                raise Engine2SuiteError("suite", "schedule seeds must be unique")
            seen_seeds.add(seed)
            if {
                name: value for name, value in request.items()
                if name not in _SEED_SWEEP_VARYING_REQUEST_FIELDS
            } != common_coordinates:
                raise Engine2SuiteError(
                    "suite", "seed-sweep cases must share fixed execution coordinates",
                )
        counts = self.suite.counts
        failures = tuple(
            Engine2SeedSweepFailure(
                item.request["case_id"], item.case_identity,
                item.request["position"], item.request["schedule_seed"], item.status,
            )
            for item in cases if item.status != "SUCCESS"
        )
        distinct_schedules: list[str] = []
        seen: set[str] = set()
        for item in cases:
            if item.native is None:
                continue
            identity = item.native["schedule"]["identity"]
            if identity not in seen:
                seen.add(identity)
                distinct_schedules.append(identity)
        object.__setattr__(self, "schedule_seeds", tuple(item.request["schedule_seed"] for item in cases))
        object.__setattr__(self, "case_ids", tuple(item.request["case_id"] for item in cases))
        object.__setattr__(self, "case_identities", tuple(item.case_identity for item in cases))
        object.__setattr__(self, "plan_identity", self.suite.plan["plan_hash"])
        object.__setattr__(self, "attempted_cases", counts["total"])
        object.__setattr__(self, "success_count", counts["success"])
        object.__setattr__(self, "expected_failure_count", counts["expected_failure"])
        object.__setattr__(self, "unexpected_failure_count", counts["unexpected_failure"])
        object.__setattr__(self, "error_count", counts["error"])
        object.__setattr__(self, "failing_cases", failures)
        object.__setattr__(self, "schedule_artifact_identities", tuple(distinct_schedules))


def explore_engine2_seeds(request: Engine2SeedSweepRequest) -> Engine2SeedSweepOutcome:
    """Execute one finite seed sweep serially in exact supplied seed order."""
    if not isinstance(request, Engine2SeedSweepRequest):
        raise TypeError("request must be Engine2SeedSweepRequest")
    plan = Engine2SuitePlan(request._cases)
    return Engine2SeedSweepOutcome(execute_engine2_suite(plan))


__all__ = (
    "CASE_ID_FORMAT", "Engine2SeedSweepFailure", "Engine2SeedSweepOutcome",
    "Engine2SeedSweepRequest", "explore_engine2_seeds",
)
