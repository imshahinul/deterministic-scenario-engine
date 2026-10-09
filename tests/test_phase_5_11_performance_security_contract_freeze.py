from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
from time import perf_counter

import pytest

from scenario_engine.diagnostics import MAX_SEMANTIC_ADDRESS_BYTES, MAX_SEMANTIC_ADDRESS_DEPTH
from scenario_engine.dsl import DSLResourceLimitError, compile_document, parse_yaml
from scenario_engine.dsl.actor_runtime import (
    MAX_CONTROL_ROUTING_OPERATIONS_PER_SELECTION, execute_actors_internal,
)
from scenario_engine.dsl.parser import MAX_ACTORS, MAX_STEPS_PER_ACTOR, MAX_TOTAL_DECLARED_STEPS
from scenario_engine.engine2 import (
    MAX_CANONICAL_RESULT_BYTES, Engine2EvidenceError, canonical_result2_bytes,
    execute_engine2, read_result2, replay_engine2, validate_engine2,
)
from scenario_engine.schedule import (
    MAX_CANONICAL_SCHEDULE_BYTES, MAX_REPLAY_SCHEDULER_SELECTIONS_VERIFIED,
    ScheduleError, canonical_schedule_bytes, read_schedule,
)
from scenario_engine.scheduler import MAX_SCHEDULER_SELECTIONS
from scenario_engine.trace_view import render_trace_view


ROOT = Path(__file__).parents[1]
SCENARIO = """dsl_version: 2
scenario: phase5-11
clock: {start: '2026-01-01T00:00:00Z'}
initial_state: {value: 0, observed: -1}
actors:
  - id: reader
    steps:
      - id: read
        write: {observed: {$state: value}}
        transition: null
  - id: writer
    steps:
      - id: write
        write: {value: {$add: [{$state: value}, {$literal: 1}]}}
        transition: null
"""


def test_frozen_resource_ceiling_inventory_is_exact() -> None:
    assert (MAX_ACTORS, MAX_STEPS_PER_ACTOR, MAX_TOTAL_DECLARED_STEPS) == (32, 256, 4096)
    assert (MAX_SCHEDULER_SELECTIONS, MAX_CONTROL_ROUTING_OPERATIONS_PER_SELECTION) == (65536, 4096)
    assert (MAX_CANONICAL_SCHEDULE_BYTES, MAX_CANONICAL_RESULT_BYTES) == (8_388_608, 33_554_432)
    assert MAX_REPLAY_SCHEDULER_SELECTIONS_VERIFIED == 65536
    assert (MAX_SEMANTIC_ADDRESS_DEPTH, MAX_SEMANTIC_ADDRESS_BYTES) == (32, 2048)


def test_overlapping_static_limit_precedence_and_no_execution() -> None:
    def actor(name: str, count: int) -> str:
        steps = "\n".join(
            f"      - {{id: s{i}, transition: {'s' + str(i + 1) if i + 1 < count else 'null'}}}"
            for i in range(count)
        )
        return f"  - id: {name}\n    steps:\n{steps}\n"
    header = "dsl_version: 2\nscenario: bounds\nclock: {start: '2026-01-01T00:00:00Z'}\ninitial_state: {}\nactors:\n"
    with pytest.raises(DSLResourceLimitError, match="MAX_ACTORS"):
        parse_yaml(header + "".join(actor(f"a{i}", 1) for i in range(33)))
    with pytest.raises(DSLResourceLimitError, match="MAX_STEPS_PER_ACTOR"):
        parse_yaml(header + actor("one", 257))
    aggregate = "".join(actor(f"a{i}", 256) for i in range(16)) + actor("extra", 1)
    with pytest.raises(DSLResourceLimitError, match="MAX_TOTAL_DECLARED_STEPS"):
        parse_yaml(header + aggregate)


def test_hostile_evidence_fails_closed_without_repair_or_secret_disclosure() -> None:
    scenario = validate_engine2(SCENARIO)
    result, schedule = execute_engine2(scenario, "root", 7)
    secret = b"phase5-11-secret-sentinel"
    result_bytes, schedule_bytes = canonical_result2_bytes(result), canonical_schedule_bytes(schedule)
    hostile = (
        (read_result2, b"\xff"),
        (read_result2, result_bytes.replace(b'{"actors":', b'{"actors":[],"actors":', 1)),
        (read_result2, result_bytes.replace(result.result_hash.encode(), b"0" * 64)),
        (read_schedule, schedule_bytes.replace(b'{"actors":', b'{"actors":[],"actors":', 1)),
        (read_schedule, schedule_bytes.replace(schedule.schedule_hash.encode(), b"0" * 64)),
        (read_schedule, b'{"contract":"scenario.schedule/999","secret":"' + secret + b'"}'),
    )
    for reader, payload in hostile:
        with pytest.raises((Engine2EvidenceError, ScheduleError)) as caught:
            reader(payload)
        assert secret.decode() not in str(caught.value)
    assert canonical_result2_bytes(result) == result_bytes
    assert canonical_schedule_bytes(schedule) == schedule_bytes


def test_result_schedule_trace_and_replay_are_cross_process_deterministic() -> None:
    expected_scenario = validate_engine2(SCENARIO)
    expected_result, expected_schedule = execute_engine2(expected_scenario, "root", 7)
    expected = b"\n".join((
        hashlib.sha256(canonical_result2_bytes(expected_result)).hexdigest().encode(),
        hashlib.sha256(canonical_schedule_bytes(expected_schedule)).hexdigest().encode(),
        hashlib.sha256(render_trace_view(expected_result, schedule=expected_schedule)).hexdigest().encode(),
    )) + b"\n"
    code = (
        "import hashlib;from scenario_engine.engine2 import *;"
        "from scenario_engine.schedule import canonical_schedule_bytes;"
        "from scenario_engine.trace_view import render_trace_view;"
        f"s=validate_engine2({SCENARIO!r});r,q=execute_engine2(s,'root',7);replay_engine2(r,q,s);"
        "print(hashlib.sha256(canonical_result2_bytes(r)).hexdigest());"
        "print(hashlib.sha256(canonical_schedule_bytes(q)).hexdigest());"
        "print(hashlib.sha256(render_trace_view(r,schedule=q)).hexdigest())"
    )
    outputs = []
    for hash_seed in ("1", "999"):
        env = {**os.environ, "PYTHONHASHSEED": hash_seed, "PYTHONPATH": str(ROOT / "src")}
        outputs.append(subprocess.check_output([sys.executable, "-c", code], cwd=ROOT, env=env))
    assert outputs == [expected, expected]


def test_bounded_performance_characterization(capsys) -> None:
    scenario = validate_engine2(SCENARIO)
    measurements = []
    for _ in range(3):
        started = perf_counter()
        result, schedule = execute_engine2(scenario, "root", 7)
        execution = perf_counter() - started
        started = perf_counter()
        replay_engine2(result, schedule, scenario)
        replay = perf_counter() - started
        started = perf_counter()
        view = render_trace_view(result, schedule=schedule)
        trace = perf_counter() - started
        measurements.append((execution, replay, trace))
    record = {
        "marker": "PHASE5_11_CHARACTERIZATION",
        "python": platform.python_version(), "platform": platform.platform(),
        "actors": 2, "selections": len(schedule.records),
        "scenario_utf8_bytes": len(SCENARIO.encode()),
        "schedule_bytes": len(canonical_schedule_bytes(schedule)),
        "result_bytes": len(canonical_result2_bytes(result)), "trace_view_bytes": len(view),
        "execution_seconds": [round(item[0], 9) for item in measurements],
        "replay_seconds": [round(item[1], 9) for item in measurements],
        "trace_seconds": [round(item[2], 9) for item in measurements],
        "interpretation": "characterization-only; no normative threshold or historical baseline",
    }
    print(json.dumps(record, sort_keys=True))
    assert "PHASE5_11_CHARACTERIZATION" in capsys.readouterr().out
