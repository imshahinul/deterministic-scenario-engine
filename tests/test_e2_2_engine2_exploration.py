from __future__ import annotations

from dataclasses import FrozenInstanceError
import os
from pathlib import Path
import subprocess
import sys

import pytest

from scenario_engine.engine2 import (
    canonical_manifest2_bytes, canonical_result2_bytes, execute_engine2,
    replay_engine2, validate_engine2,
)
from scenario_engine.engine2_explore import (
    CASE_ID_FORMAT, Engine2SeedSweepOutcome, Engine2SeedSweepRequest,
    explore_engine2_seeds,
)
from scenario_engine.engine2_suite import (
    MAX_CASE_INPUT_BYTES, Engine2CaseOutcome, Engine2CaseRequest,
    Engine2SuiteBoundError, Engine2SuiteError, Engine2SuitePlan,
    Engine2SuiteVerificationError, canonical_engine2_suite_bytes,
    execute_engine2_suite, read_engine2_suite, verify_engine2_suite,
)
from scenario_engine.plugins import GeneratorPlugin, PluginRegistry
from scenario_engine.schedule import canonical_schedule_bytes
from scenario_engine.scheduler import MAX_SCHEDULE_SEED


ROOT = Path(__file__).parents[1]


def source(*, failing: bool = False, plugin: bool = False, resources: bool = False) -> str:
    generation = (
        "        generate:\n"
        "          made: {$plugin: {name: test.counter, version: '1', args: {}}}\n"
        if plugin else ""
    )
    resource = "resources:\n  supplied: {$input: supplied}\n" if resources else ""
    invariant = (
        "invariants:\n"
        "  - id: bounded\n"
        "    check: {$lte: [{$state: value}, {$literal: 0}]}\n"
        if failing else ""
    )
    return (
        "dsl_version: 2\nscenario: engine2-seed-sweep\n"
        "clock: {start: '2026-01-01T00:00:00Z'}\n"
        "initial_state: {value: 0}\n" + resource +
        "actors:\n  - id: actor\n    steps:\n      - id: write\n" + generation +
        "        write: {value: {$add: [{$state: value}, {$literal: 1}]}}\n"
        "        transition: null\n" + invariant
    )


def schedule_dependent_source() -> str:
    return """dsl_version: 2
scenario: schedule-dependent
clock: {start: '2026-01-01T00:00:00Z'}
initial_state: {winner: none}
actors:
  - id: alpha
    steps:
      - id: write
        write: {winner: {$literal: alpha}}
        transition: null
  - id: beta
    steps:
      - id: write
        write: {winner: {$literal: beta}}
        transition: null
"""


def request(seeds=(7,), **changes) -> Engine2SeedSweepRequest:
    values = {
        "scenario": validate_engine2(source()), "root_seed": "root",
        "schedule_seeds": seeds, "run_index": 3,
    }
    values.update(changes)
    return Engine2SeedSweepRequest(**values)


def children(outcome: Engine2SeedSweepOutcome):
    return {
        item.request["case_id"]: {
            "manifest": canonical_manifest2_bytes(item.result.manifest),
            "result": canonical_result2_bytes(item.result),
            "schedule": canonical_schedule_bytes(item.schedule),
        }
        for item in outcome.suite.cases if item.result is not None
    }


def ordinary_suite(*cases: Engine2CaseRequest):
    return execute_engine2_suite(Engine2SuitePlan(cases))


def test_single_seed_sweep_and_immutable_suite_derived_summary() -> None:
    outcome = explore_engine2_seeds(request())
    assert outcome.schedule_seeds == (7,)
    assert outcome.case_ids == (CASE_ID_FORMAT.format(position=0),)
    assert outcome.case_identities == tuple(outcome.suite.plan["case_identities"])
    assert outcome.plan_identity == outcome.suite.plan["plan_hash"]
    assert (outcome.attempted_cases, outcome.success_count) == (1, 1)
    assert (outcome.expected_failure_count, outcome.unexpected_failure_count, outcome.error_count) == (0, 0, 0)
    with pytest.raises(FrozenInstanceError):
        outcome.success_count = 0  # type: ignore[misc]


def test_outcome_direct_construction_rejects_valid_ordinary_suite_case_ids() -> None:
    scenario = validate_engine2(source())
    suite = ordinary_suite(
        Engine2CaseRequest("ordinary-a", scenario, "root", 1),
        Engine2CaseRequest("ordinary-b", scenario, "root", 2),
    )
    with pytest.raises(Engine2SuiteError, match="ordered seed-sweep format"):
        Engine2SeedSweepOutcome(suite)


def test_outcome_direct_construction_rejects_duplicate_schedule_seeds() -> None:
    scenario = validate_engine2(source())
    suite = ordinary_suite(
        Engine2CaseRequest("seed-sweep-00", scenario, "root", 1),
        Engine2CaseRequest("seed-sweep-01", scenario, "root", 1),
    )
    with pytest.raises(Engine2SuiteError, match="schedule seeds must be unique"):
        Engine2SeedSweepOutcome(suite)


def test_outcome_direct_construction_rejects_differing_root_seeds() -> None:
    scenario = validate_engine2(source())
    suite = ordinary_suite(
        Engine2CaseRequest("seed-sweep-00", scenario, "root-a", 1),
        Engine2CaseRequest("seed-sweep-01", scenario, "root-b", 2),
    )
    with pytest.raises(Engine2SuiteError, match="fixed execution coordinates"):
        Engine2SeedSweepOutcome(suite)


def test_outcome_direct_construction_rejects_differing_run_indices() -> None:
    scenario = validate_engine2(source())
    suite = ordinary_suite(
        Engine2CaseRequest("seed-sweep-00", scenario, "root", 1, run_index=3),
        Engine2CaseRequest("seed-sweep-01", scenario, "root", 2, run_index=4),
    )
    with pytest.raises(Engine2SuiteError, match="fixed execution coordinates"):
        Engine2SeedSweepOutcome(suite)


def test_outcome_direct_construction_rejects_differing_scenarios_or_inputs() -> None:
    first_scenario = validate_engine2(source())
    differing_scenario = ordinary_suite(
        Engine2CaseRequest("seed-sweep-00", first_scenario, "root", 1),
        Engine2CaseRequest(
            "seed-sweep-01", validate_engine2(schedule_dependent_source()), "root", 2,
        ),
    )
    resource_scenario = validate_engine2(source(resources=True))
    differing_inputs = ordinary_suite(
        Engine2CaseRequest(
            "seed-sweep-00", resource_scenario, "root", 1, inputs={"supplied": 1},
        ),
        Engine2CaseRequest(
            "seed-sweep-01", resource_scenario, "root", 2, inputs={"supplied": 2},
        ),
    )
    for suite in (differing_scenario, differing_inputs):
        with pytest.raises(Engine2SuiteError, match="fixed execution coordinates"):
            Engine2SeedSweepOutcome(suite)


def test_outcome_direct_construction_accepts_genuine_sweep_without_execution(monkeypatch) -> None:
    outcome = explore_engine2_seeds(request([9, 2, 7]))

    def unexpected_execution(_plan):
        raise AssertionError("outcome validation must not execute a suite")

    monkeypatch.setattr("scenario_engine.engine2_explore.execute_engine2_suite", unexpected_execution)
    reconstructed = Engine2SeedSweepOutcome(outcome.suite)
    assert reconstructed.schedule_seeds == (9, 2, 7)
    assert reconstructed.case_identities == outcome.case_identities


def test_order_coordinates_standalone_equivalence_and_state_isolation() -> None:
    scenario = validate_engine2(source(resources=True))
    supplied = {"supplied": {"private": 3}}
    outcome = explore_engine2_seeds(Engine2SeedSweepRequest(
        scenario, "fixed-root", [9, 2, 7], 11, inputs=supplied,
    ))
    assert outcome.schedule_seeds == (9, 2, 7)
    assert outcome.case_ids == ("seed-sweep-00", "seed-sweep-01", "seed-sweep-02")
    for case, seed in zip(outcome.suite.cases, (9, 2, 7)):
        assert case.request["root_seed"] == "fixed-root"
        assert case.request["run_index"] == 11
        assert case.request["input_hash"] == outcome.suite.cases[0].request["input_hash"]
        assert case.request["input_resource_hashes"] == outcome.suite.cases[0].request["input_resource_hashes"]
        standalone = execute_engine2(scenario, "fixed-root", seed, run_index=11, inputs=supplied)
        assert canonical_result2_bytes(case.result) == canonical_result2_bytes(standalone[0])
        assert canonical_schedule_bytes(case.schedule) == canonical_schedule_bytes(standalone[1])
        assert case.result.final_state["value"] == 1


def test_repeat_determinism_reordering_and_seed_identity() -> None:
    first = explore_engine2_seeds(request([1, 2, 3]))
    again = explore_engine2_seeds(request([1, 2, 3]))
    reordered = explore_engine2_seeds(request([3, 2, 1]))
    changed = explore_engine2_seeds(request([1, 4, 3]))
    assert canonical_engine2_suite_bytes(first.suite) == canonical_engine2_suite_bytes(again.suite)
    assert first.plan_identity != reordered.plan_identity
    assert first.case_identities[0] != reordered.case_identities[0]
    assert first.case_identities[1] == reordered.case_identities[1]
    assert first.case_ids == changed.case_ids
    assert first.case_identities[1] != changed.case_identities[1]


def test_native_children_verify_and_every_completed_case_replays() -> None:
    sweep = request([0, 1, 2])
    outcome = explore_engine2_seeds(sweep)
    encoded = canonical_engine2_suite_bytes(outcome.suite)
    read = read_engine2_suite(encoded)
    assert verify_engine2_suite(read, children(outcome)).aggregate_hash == outcome.suite.aggregate_hash
    for case in outcome.suite.cases:
        assert replay_engine2(
            case.result, case.schedule, sweep.scenario,
            inputs=None if sweep.inputs is None else dict(sweep.inputs), plugins=sweep.plugins,
        ) == case.result


def test_expected_unexpected_and_error_results_are_preserved_and_counted() -> None:
    expected = explore_engine2_seeds(request(
        [1, 2], scenario=validate_engine2(source(failing=True)),
        expected_classification="FAILED", expected_failure_code="InvariantViolation",
    ))
    unexpected = explore_engine2_seeds(request(
        [3], scenario=validate_engine2(source(failing=True)),
    ))
    secret = "PRIVATE-PLUGIN-ERROR"
    registry = PluginRegistry((GeneratorPlugin(
        "test.counter", "1", lambda *_: (_ for _ in ()).throw(RuntimeError(secret)),
    ),))
    errored = explore_engine2_seeds(request(
        [4], scenario=validate_engine2(source(plugin=True)), plugins=registry,
    ))
    assert [item.status for item in expected.suite.cases] == ["EXPECTED_FAILURE", "EXPECTED_FAILURE"]
    assert all(item.result.classification == "FAILED" for item in expected.suite.cases)
    assert expected.expected_failure_count == 2 and len(expected.failing_cases) == 2
    assert unexpected.unexpected_failure_count == 1
    assert unexpected.failing_cases[0].schedule_seed == 3
    assert errored.error_count == 1 and errored.suite.cases[0].native is None
    assert errored.failing_cases[0].status == "ERROR"
    assert secret.encode() not in canonical_engine2_suite_bytes(errored.suite)


def test_controlled_supported_dsl_has_known_schedule_dependent_outcome() -> None:
    scenario = validate_engine2(schedule_dependent_source())
    outcome = explore_engine2_seeds(Engine2SeedSweepRequest(scenario, "root", [0, 1], 4))
    assert [case.result.final_state["winner"] for case in outcome.suite.cases] == ["beta", "alpha"]
    assert len(outcome.schedule_artifact_identities) == 2


@pytest.mark.parametrize("seeds", [[], list(range(65))])
def test_seed_count_bounds(seeds) -> None:
    with pytest.raises(Engine2SuiteError, match="1..64"):
        request(seeds)


@pytest.mark.parametrize("seeds", [[1, 1], [-1], [MAX_SCHEDULE_SEED + 1], [True], ["1"], [1.0]])
def test_invalid_seed_values(seeds) -> None:
    with pytest.raises(Engine2SuiteError):
        request(seeds)


@pytest.mark.parametrize("seeds", [{1, 2}, frozenset({1, 2}), (seed for seed in (1, 2)), {"a": 1}])
def test_unordered_and_lazy_seed_collections_are_rejected_without_materialization(seeds) -> None:
    with pytest.raises(Engine2SuiteError, match="explicit ordered"):
        request(seeds)


@pytest.mark.parametrize("root_seed", [True, None, 1.5])
def test_invalid_root_seed_is_rejected_by_case_contract(root_seed) -> None:
    with pytest.raises(Engine2SuiteError):
        request(root_seed=root_seed)


def test_invalid_compatibility_and_unsupported_plugin_requirements() -> None:
    with pytest.raises(Engine2SuiteError):
        Engine2SeedSweepRequest(object(), "root", [1], 0)  # type: ignore[arg-type]
    scenario = validate_engine2(source(plugin=True))
    with pytest.raises(Engine2SuiteError):
        Engine2SeedSweepRequest(scenario, "root", [1], 0)
    wrong = PluginRegistry((GeneratorPlugin("test.counter", "2", lambda *_: 1),))
    with pytest.raises(Engine2SuiteError):
        Engine2SeedSweepRequest(scenario, "root", [1], 0, plugins=wrong)


def test_existing_input_bound_fails_closed_before_execution() -> None:
    scenario = validate_engine2(source(resources=True))
    with pytest.raises(Engine2SuiteBoundError):
        Engine2SeedSweepRequest(
            scenario, "root", [1], 0,
            inputs={"supplied": "x" * (MAX_CASE_INPUT_BYTES + 1)},
        )


def test_tampered_or_missing_native_evidence_fails_existing_verifier() -> None:
    outcome = explore_engine2_seeds(request([1, 2]))
    evidence = children(outcome)
    missing = {next(iter(evidence)): next(iter(evidence.values()))}
    with pytest.raises(Engine2SuiteVerificationError):
        verify_engine2_suite(outcome.suite, missing)
    tampered = {key: dict(value) for key, value in evidence.items()}
    first = next(iter(tampered))
    tampered[first]["schedule"] += b" "
    with pytest.raises(Engine2SuiteVerificationError):
        verify_engine2_suite(outcome.suite, tampered)


def test_completed_failure_cannot_be_forged_as_success() -> None:
    outcome = explore_engine2_seeds(request(
        scenario=validate_engine2(source(failing=True)),
        expected_classification="FAILED", expected_failure_code="InvariantViolation",
    ))
    case = outcome.suite.cases[0]
    with pytest.raises(Engine2SuiteError, match="observation and expectation"):
        Engine2CaseOutcome(
            case.request, case.case_identity, "SUCCESS", case.observed, case.native, None,
        )


def test_cross_process_pythonhashseed_determinism() -> None:
    code = f'''from scenario_engine.engine2 import validate_engine2
from scenario_engine.engine2_explore import Engine2SeedSweepRequest, explore_engine2_seeds
from scenario_engine.engine2_suite import canonical_engine2_suite_bytes
s=validate_engine2({source()!r})
o=explore_engine2_seeds(Engine2SeedSweepRequest(s,"root",[9,2,7],3))
print(canonical_engine2_suite_bytes(o.suite).hex())'''
    outputs = []
    for seed in ("1", "999"):
        environment = {
            **os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONHASHSEED": seed,
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        outputs.append(subprocess.check_output([sys.executable, "-c", code], cwd=ROOT, env=environment))
    assert outputs[0] == outputs[1]
