from __future__ import annotations

from scenario_engine.address import ExecutionAddress
from scenario_engine.canonical import canonical_scenario_hash
from scenario_engine.clock import LogicalClock
from scenario_engine.ids import ID_VERSION
from scenario_engine.manifest import (
    ENGINE_VERSION, GENERATOR_VERSIONS, ReplayCompatibilityError,
    ReproducibilityManifest,
)
from scenario_engine.result import ScenarioResult
from scenario_engine.rng import RNG_VERSION
from scenario_engine.runner import ScenarioRunner
from scenario_engine.state import ScenarioState

from .compiler import compile_document
from .errors import DSLCompilationError
from .models import CompiledScenario
from .parser import parse_yaml


def run_scenario(
    scenario: CompiledScenario,
    root_seed: str | int,
    run_index: int = 0,
    locale: str = "C",
) -> ScenarioResult:
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
    manifest = ReproducibilityManifest(
        root_seed=root_seed,
        scenario_canonical_hash=canonical_scenario_hash(scenario),
        engine_version=ENGINE_VERSION,
        dsl_version=scenario.document.dsl_version,
        generator_versions=GENERATOR_VERSIONS,
        rng_algorithm_version=RNG_VERSION,
        id_algorithm_version=ID_VERSION,
        locale=locale,
        reference_clock_start=scenario.reference_clock_start,
        run_index=run_index,
    )
    return ScenarioResult(scenario.scenario_id, runner, manifest)


def replay_scenario(yaml_text: str, manifest: ReproducibilityManifest) -> ScenarioResult:
    scenario = compile_document(parse_yaml(yaml_text))
    expected = {
        "scenario_canonical_hash": canonical_scenario_hash(scenario),
        "engine_version": ENGINE_VERSION,
        "dsl_version": scenario.document.dsl_version,
        "rng_algorithm_version": RNG_VERSION,
        "id_algorithm_version": ID_VERSION,
        "generator_versions": GENERATOR_VERSIONS,
        "reference_clock_start": scenario.reference_clock_start,
    }
    for field_name, current in expected.items():
        if getattr(manifest, field_name) != current:
            raise ReplayCompatibilityError(f"{field_name} mismatch")
    if manifest.input_resource_hashes:
        raise ReplayCompatibilityError("input_resource_hashes unsupported in Phase 0.2A")
    if manifest.domain_pack_versions:
        raise ReplayCompatibilityError("domain_pack_versions unsupported in Phase 0.2A")
    return run_scenario(
        scenario, manifest.root_seed, manifest.run_index, locale=manifest.locale,
    )
