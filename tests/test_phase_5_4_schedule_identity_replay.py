from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from scenario_engine.dsl import UnsupportedDSL2ExecutionError, compile_document, parse_yaml, run_scenario
from scenario_engine.dsl.actor_runtime import execute_actors_internal
from scenario_engine.invariants import InvariantViolation
from scenario_engine.schedule import (
    MAX_CANONICAL_SCHEDULE_BYTES, ScheduleBoundError, ScheduleError,
    ScheduleReplayMismatch, canonical_schedule_bytes, canonical_schedule_identity_bytes,
    exact_replay_internal, read_schedule,
)


ROOT = Path(__file__).parents[1]
WRITE = "      - id: write\n        write: {value: {$add: [{$state: value}, {$literal: 1}]}}\n        advance: {seconds: 1}\n        transition: null\n"
READ = "      - id: read\n        write: {observed: {$state: value}}\n        transition: null\n"


def actor(name: str, steps: str) -> str:
    return f"  - id: {name}\n    steps:\n{steps}"


def scenario(actors: str | None = None, extra: str = ""):
    raw = (
        "dsl_version: 2\nscenario: schedule-case\nclock: {start: '2026-01-01T00:00:00Z'}\n"
        "initial_state: {value: 0, observed: -1}\nactors:\n"
        + (actors or actor("reader", READ) + actor("writer", WRITE)) + extra
    )
    return compile_document(parse_yaml(raw)), raw


def produced(seed: int = 7):
    compiled, _ = scenario()
    outcome = execute_actors_internal(compiled, "root", seed)
    return compiled, outcome, outcome.schedule


def mutate(schedule, **changes):
    payload = json.loads(canonical_schedule_bytes(schedule))
    payload.update(changes)
    payload.pop("schedule_hash", None)
    payload["schedule_hash"] = hashlib.sha256(json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True,
    ).encode()).hexdigest()
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()


def test_t01_t10_canonical_artifact_hash_records_and_coordinates() -> None:
    _, outcome, schedule = produced()
    encoded = canonical_schedule_bytes(schedule)
    assert read_schedule(encoded) == schedule
    assert schedule.schedule_hash == hashlib.sha256(canonical_schedule_identity_bytes(schedule)).hexdigest()
    assert encoded == canonical_schedule_bytes(produced()[2])
    assert [record.selection_ordinal for record in schedule.records] == list(range(len(schedule.records)))
    assert [record.selected_actor for record in schedule.records] == [
        decision.selected_actor for decision in outcome.scheduling_decisions
    ]
    assert all(record.ready_actors == tuple(sorted(record.ready_actors, key=str.encode)) for record in schedule.records)
    assert [record.committed_history_length for record in schedule.records] == [0, 1]
    assert schedule.records[1].logical_clock == outcome.committed_history[0].logical_timestamp


def test_t04_independent_fixed_golden_bytes_digest_and_selections() -> None:
    # Literal expectation verified by a standalone stdlib script, not schedule.py.
    _, _, schedule = produced(7)
    assert [item.selected_actor for item in schedule.records] == [
        "scenario:/actor/writer", "scenario:/actor/reader",
    ]
    identity = (
        b'{"actors":["scenario:/actor/reader","scenario:/actor/writer"],"contract":"scenario.schedule/1",'
        b'"execution":{"dsl_version":2,"engine_version":"2.0.0","generator_versions":{"int":'
        b'"scenario-engine-addressed-v1","logical_id":"scenario-engine-id-v1"},"id_algorithm_version":'
        b'"scenario-engine-id-v1","locale":"C","reference_clock_start":{"$type":"datetime","value":'
        b'"2026-01-01T00:00:00.000000+00:00"},"rng_algorithm_version":"scenario-engine-addressed-v1",'
        b'"root_seed":"root"},"input_resource_hashes":{},"records":[{"committed_history_length":0,'
        b'"logical_clock":{"$type":"datetime","value":"2026-01-01T00:00:00.000000+00:00"},"outcome":'
        b'"COMMITTED","ready_actors":["scenario:/actor/reader","scenario:/actor/writer"],"scheduler_digest":'
        b'"2d3f1fa83d4634ed4a3394781dea16172840a3862b2fe5580f00619652c15bf3","selected_actor":'
        b'"scenario:/actor/writer","selection_ordinal":0},{"committed_history_length":1,"logical_clock":'
        b'{"$type":"datetime","value":"2026-01-01T00:00:01.000000+00:00"},"outcome":"COMMITTED",'
        b'"ready_actors":["scenario:/actor/reader"],"scheduler_digest":'
        b'"8568335abac76afa22a94a376a68c14d8c9643cb33729fd1ead0514ace261345","selected_actor":'
        b'"scenario:/actor/reader","selection_ordinal":1}],"run_index":0,"scenario_hash":'
        b'"646586d7457c1b27d2ea9d8c21fb80459391c776565533654c9600b0d6728c84","schedule_seed":7,'
        b'"scheduler_contract":"scenario.scheduler/1","terminal":{"classification":"SUCCESS","failure":null}}'
    )
    assert hashlib.sha256(identity).hexdigest() == "23440b74a2e3710ca10946eb171b685fa515ba0c4da87e9e890aec51efd7eaa6"
    assert canonical_schedule_identity_bytes(schedule) == identity


def test_t11_t16_top_level_coordinate_and_actor_mismatches_fail_closed() -> None:
    compiled, _, schedule = produced()
    other_seed = execute_actors_internal(compiled, "root", 8).schedule
    assert schedule.schedule_seed != other_seed.schedule_seed
    for field, value in (
        ("scenario_hash", "f" * 64), ("input_resource_hashes", {"resource:x": "f" * 64}),
        ("run_index", 1), ("scheduler_contract", "scenario.scheduler/999"),
        ("actors", ["scenario:/actor/unknown"]),
    ):
        with pytest.raises((ScheduleError, ScheduleReplayMismatch)):
            exact_replay_internal(mutate(schedule, **{field: value}), compiled)


@pytest.mark.parametrize("kind", ["selection", "ready", "missing", "extra", "reordered"])
def test_t17_t21_record_tampering_is_rejected(kind: str) -> None:
    compiled, _, schedule = produced()
    payload = json.loads(canonical_schedule_bytes(schedule))
    records = payload["records"]
    if kind == "selection":
        records[0]["selected_actor"] = next(
            actor for actor in records[0]["ready_actors"] if actor != records[0]["selected_actor"]
        )
    elif kind == "ready": records[0]["ready_actors"] = ["scenario:/actor/reader"]
    elif kind == "missing": records.pop()
    elif kind == "extra": records.append(dict(records[-1], selection_ordinal=2))
    else: records.reverse(); records[0]["selection_ordinal"], records[1]["selection_ordinal"] = 0, 1
    payload.pop("schedule_hash")
    with pytest.raises((ScheduleError, ScheduleReplayMismatch)):
        exact_replay_internal(mutate(schedule, records=records), compiled)


def test_t22_t26_corruption_versions_duplicate_keys_and_coordinate_types() -> None:
    _, _, schedule = produced()
    encoded = canonical_schedule_bytes(schedule)
    with pytest.raises(ScheduleError, match="schedule_hash"):
        read_schedule(encoded.replace(schedule.schedule_hash.encode(), b"0" * 64))
    with pytest.raises(ScheduleError, match="contract"):
        read_schedule(mutate(schedule, contract="scenario.schedule/999"))
    duplicate = encoded.replace(b'{"actors":', b'{"actors":[],"actors":', 1)
    with pytest.raises(ScheduleError, match="duplicate"):
        read_schedule(duplicate)
    with pytest.raises(ScheduleError, match="run_index"):
        read_schedule(mutate(schedule, run_index=True))


def test_t27_t30_exact_replay_equivalence_and_schedule_sensitive_outcomes() -> None:
    compiled, outcome, schedule = produced(7)
    replay = exact_replay_internal(schedule, compiled)
    assert replay.scheduling_decisions == outcome.scheduling_decisions
    assert replay.committed_history == outcome.committed_history
    assert replay.final_state == outcome.final_state
    assert replay.final_logical_clock == outcome.final_logical_clock
    assert replay.actor_states == outcome.actor_states
    observed = {execute_actors_internal(compiled, "root", seed).final_state["observed"] for seed in range(20)}
    assert observed == {0, 1}


def test_t31_t32_failed_selection_is_recorded_without_partial_commit_and_replays() -> None:
    extra = "invariants:\n  - id: bounded\n    check: {$lte: [{$state: value}, {$literal: 0}]}\n"
    compiled, _ = scenario(actor("bad", WRITE) + actor("other", READ), extra)
    for seed in range(50):
        try:
            execute_actors_internal(compiled, "root", seed)
        except InvariantViolation as error:
            outcome = error.internal_outcome
            if not outcome.committed_history:
                assert outcome.schedule.classification == "FAILED"
                assert outcome.schedule.records[-1].outcome == "FAILED"
                replay = exact_replay_internal(outcome.schedule, compiled)
                assert replay.final_state == outcome.final_state
                return
    pytest.fail("no bounded seed selected failing actor first")


def test_t33_t36_count_size_malformed_and_oversized_bounds(monkeypatch) -> None:
    import scenario_engine.schedule as module
    _, _, schedule = produced()
    monkeypatch.setattr(module, "MAX_REPLAY_SCHEDULER_SELECTIONS_VERIFIED", 1)
    with pytest.raises(ScheduleBoundError): read_schedule(canonical_schedule_bytes(schedule))
    with pytest.raises(ScheduleError): read_schedule(b"{")
    with pytest.raises(ScheduleBoundError): read_schedule(b" " * (MAX_CANONICAL_SCHEDULE_BYTES + 1))
    monkeypatch.setattr(module, "MAX_CANONICAL_SCHEDULE_BYTES", 1)
    with pytest.raises(ScheduleBoundError): canonical_schedule_bytes(schedule)


def test_t37_t38_source_and_nested_schedule_records_are_immutable() -> None:
    compiled, _, schedule = produced()
    before = canonical_schedule_bytes(schedule)
    exact_replay_internal(schedule, compiled)
    assert canonical_schedule_bytes(schedule) == before
    with pytest.raises(FrozenInstanceError): schedule.records[0].outcome = "FAILED"  # type: ignore[misc]
    with pytest.raises(TypeError): schedule.input_resource_hashes["x"] = "y"  # type: ignore[index]


def test_t39_t40_python_hash_seed_and_cross_process_replay_are_identical() -> None:
    compiled, raw = scenario()
    expected = canonical_schedule_bytes(execute_actors_internal(compiled, "root", 7).schedule)
    code = f'''from scenario_engine.dsl import parse_yaml,compile_document
from scenario_engine.dsl.actor_runtime import execute_actors_internal
from scenario_engine.schedule import canonical_schedule_bytes,exact_replay_internal
s=compile_document(parse_yaml({raw!r})); o=execute_actors_internal(s,"root",7); r=exact_replay_internal(o.schedule,s)
print(canonical_schedule_bytes(r.schedule).hex())'''
    outputs = []
    for seed in ("1", "999"):
        environment = os.environ.copy(); environment.update({"PYTHONHASHSEED": seed, "PYTHONPATH": str(ROOT / "src")})
        outputs.append(subprocess.check_output([sys.executable, "-c", code], cwd=ROOT, env=environment).strip())
    assert outputs == [expected.hex().encode(), expected.hex().encode()]


def test_t43_t49_public_surface_and_redacted_filesystem_boundary() -> None:
    compiled, _, schedule = produced()
    with pytest.raises(UnsupportedDSL2ExecutionError): run_scenario(compiled, "root")
    import scenario_engine
    assert not hasattr(scenario_engine, "ScheduleArtifact")
    assert b"/Users/" not in canonical_schedule_bytes(schedule)
    hostile = mutate(schedule, scenario_hash="/tmp/secret")
    with pytest.raises(ScheduleError) as error: read_schedule(hostile)
    assert "/tmp/secret" not in str(error.value)
