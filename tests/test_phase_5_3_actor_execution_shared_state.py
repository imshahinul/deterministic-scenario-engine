from __future__ import annotations

from dataclasses import FrozenInstanceError
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from scenario_engine.dsl import compile_document, parse_yaml, run_scenario, UnsupportedDSL2ExecutionError
from scenario_engine.dsl.actor_runtime import (
    ActorExecutionError, execute_actors_internal,
)
from scenario_engine.invariants import InvariantViolation


ROOT = Path(__file__).parents[1]


def scenario(actors: str, *, initial: str = "{value: 0, observed: -1}", extra: str = ""):
    raw = (
        "dsl_version: 2\nscenario: shared\nclock: {start: '2026-01-01T00:00:00Z'}\n"
        f"initial_state: {initial}\nactors:\n{actors}{extra}"
    )
    return compile_document(parse_yaml(raw)), raw


def actor(name: str, steps: str) -> str:
    return f"  - id: {name}\n    steps:\n{steps}"


WRITE = "      - id: write\n        write: {value: {$add: [{$state: value}, {$literal: 1}]}}\n        advance: {seconds: 1}\n        transition: null\n"
READ = "      - id: read\n        write: {observed: {$state: value}}\n        transition: null\n"


def run(seed=0, *, root="generation", actors=None, extra=""):
    compiled, _ = scenario(actors or (actor("reader", READ) + actor("writer", WRITE)), extra=extra)
    return execute_actors_internal(compiled, root, seed)


def test_two_actors_share_state_and_schedule_sensitive_atomic_read_write() -> None:
    outcomes = {seed: run(seed) for seed in range(20)}
    observed = {item.final_state["observed"] for item in outcomes.values()}
    assert observed == {0, 1}
    for item in outcomes.values():
        assert item.final_state["value"] == 1
        assert len(item.committed_history) == 2


def test_one_ready_actor_order_position_completion_history_clock_and_addresses() -> None:
    steps = (
        "      - id: first\n        write: {value: {$literal: 1}}\n        advance: {seconds: 2}\n        transition: second\n"
        "      - id: second\n        write: {value: {$add: [{$state: value}, {$literal: 1}]}}\n        advance: {seconds: 3}\n        transition: null\n"
    )
    result = run(actors=actor("solo", steps))
    assert result.classification == "SUCCESS" and result.final_state["value"] == 2
    assert [record.address.step_id for record in result.committed_history] == ["first", "second"]
    assert [record.address.semantic() for record in result.committed_history] == [
        "scenario:/actor/solo/step/first", "scenario:/actor/solo/step/second",
    ]
    assert result.final_logical_clock.isoformat() == "2026-01-01T00:00:05+00:00"
    assert result.actor_states[0].terminal is True


def test_scheduler_ready_order_and_coordinates_track_global_commits() -> None:
    result = run(7)
    assert all(item.ready_actors == tuple(sorted(item.ready_actors, key=str.encode)) for item in result.scheduling_decisions)
    assert [item.ordinal for item in result.scheduling_decisions] == [0, 1]
    assert [item.committed_history_length for item in result.scheduling_decisions] == [0, 1]
    assert result.scheduling_decisions[1].logical_clock == result.committed_history[0].logical_timestamp


def test_same_coordinates_repeat_exactly_and_different_seeds_are_deterministic() -> None:
    first, second = run(9), run(9)
    assert first == second
    assert run(10) == run(10)


def test_generation_seed_is_independent_from_schedule_seed_and_actor_rng_is_scoped() -> None:
    generated = "      - id: generate\n        generate: {number: {$int: [1, 1000000]}}\n        write: {value: {$local: number}}\n        transition: null\n"
    actors = actor("alpha", generated) + actor("beta", generated)
    one, two = run(1, root="same", actors=actors), run(2, root="same", actors=actors)
    values_one = {r.address.actor_id: r.state_patch["value"] for r in one.committed_history}
    values_two = {r.address.actor_id: r.state_patch["value"] for r in two.committed_history}
    assert values_one == values_two
    assert values_one["alpha"] != values_one["beta"]


def test_failed_invariant_is_atomic_and_stops_other_actors() -> None:
    extra = "invariants:\n  - id: bounded\n    check: {$lte: [{$state: value}, {$literal: 0}]}\n"
    compiled, _ = scenario(actor("bad", WRITE) + actor("other", READ), extra=extra)
    # Find a deterministic seed selecting the failing writer first.
    for seed in range(50):
        try:
            execute_actors_internal(compiled, "root", seed)
        except InvariantViolation as error:
            outcome = error.internal_outcome
            if not outcome.committed_history:
                assert outcome.final_state == {"value": 0, "observed": -1}
                assert outcome.final_logical_clock.isoformat() == "2026-01-01T00:00:00+00:00"
                assert error.actor_address == "scenario:/actor/bad"
                return
    pytest.fail("no bounded seed selected the failing actor first")


def test_faults_apply_in_declaration_order_before_invariants_and_commit_atomically() -> None:
    extra = (
        "faults:\n"
        "  - id: first\n    enabled: true\n    at: before_step\n    selector: {step: write}\n"
        "    operator: {override_write: {path: value, value: {$literal: 2}}}\n"
        "  - id: second\n    enabled: true\n    at: before_step\n    selector: {step: write}\n"
        "    operator: {override_write: {path: value, value: {$literal: 3}}}\n"
        "invariants:\n  - id: exact\n    check: {$eq: [{$state: value}, {$literal: 3}]}\n"
    )
    result = run(actors=actor("faulted", WRITE), extra=extra)
    assert result.final_state["value"] == 3
    assert result.committed_history[0].faults_applied == ("first", "second")


def test_control_routing_call_branch_repeat_is_finite_and_preserves_actor_position() -> None:
    body = (
        "      - id: choose\n        branch:\n          cases:\n            - when: {$eq: [{$state: value}, {$literal: 0}]}\n              subflow: add\n        transition: loop\n"
        "      - id: loop\n        repeat: {count: {$literal: 2}, max: 2, subflow: add}\n        transition: null\n"
        "    subflows:\n      add:\n        steps:\n          - id: increment\n            write: {value: {$add: [{$state: value}, {$literal: 1}]}}\n            transition: null\n"
    )
    result = run(actors=actor("control", body))
    assert result.final_state["value"] == 3
    assert len(result.committed_history) == 3


def test_internal_outcome_and_nested_state_are_immutable() -> None:
    result = run()
    with pytest.raises(FrozenInstanceError):
        result.classification = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        result.final_state["value"] = 4  # type: ignore[index]


def test_selection_and_control_bounds_reject_before_excess(monkeypatch) -> None:
    import scenario_engine.dsl.actor_runtime as runtime
    two = "      - {id: one, transition: two}\n      - {id: two, transition: null}\n"
    monkeypatch.setattr(runtime, "MAX_SCHEDULER_SELECTIONS", 1)
    compiled, _ = scenario(actor("bounded", two))
    with pytest.raises(ActorExecutionError, match="before creating") as selected:
        execute_actors_internal(compiled, "root", 0)
    assert selected.value.limit == "MAX_SCHEDULER_SELECTIONS"
    monkeypatch.setattr(runtime, "MAX_CONTROL_ROUTING_OPERATIONS_PER_SELECTION", 0)
    with pytest.raises(ActorExecutionError, match="before transition") as routed:
        execute_actors_internal(compiled, "root", 0)
    assert routed.value.limit == "MAX_CONTROL_ROUTING_OPERATIONS_PER_SELECTION"


def test_public_dsl2_run_stays_unsupported_and_no_public_v2_artifact_exists() -> None:
    compiled, _ = scenario(actor("one", WRITE))
    with pytest.raises(UnsupportedDSL2ExecutionError):
        run_scenario(compiled, "root")
    result = execute_actors_internal(compiled, "root", 0)
    assert not hasattr(result, "schema") and not hasattr(result, "manifest")


def test_cross_process_hash_seed_normalized_outcome_agrees() -> None:
    code = f'''\nimport json\nfrom scenario_engine.dsl import parse_yaml,compile_document\nfrom scenario_engine.dsl.actor_runtime import execute_actors_internal\ns={scenario(actor("reader", READ)+actor("writer", WRITE))[1]!r}\nr=execute_actors_internal(compile_document(parse_yaml(s)),"root",3)\nprint(json.dumps({{"state":dict(r.final_state),"actors":[x.selected_actor for x in r.scheduling_decisions],"history":[x.address.semantic() for x in r.committed_history]}},sort_keys=True))\n'''
    outputs = []
    for seed in ("1", "999"):
        environment = os.environ.copy()
        environment.update({"PYTHONHASHSEED": seed, "PYTHONPATH": str(ROOT / "src")})
        outputs.append(subprocess.check_output([sys.executable, "-c", code], cwd=ROOT, env=environment))
    assert outputs[0] == outputs[1]
