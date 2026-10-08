from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from scenario_engine.scheduler import (
    MAX_SCHEDULE_SEED, MAX_SELECTION_ORDINAL, SCHEDULER_CONTRACT,
    SchedulerInput, SchedulerValidationError, select_actor,
)


ROOT = Path(__file__).parents[1]
A = "scenario:/actor/alpha"
B = "scenario:/actor/beta"
U = "scenario:/actor/%C3%A9clair"
CLOCK = datetime(2026, 1, 1, tzinfo=timezone.utc)
ZERO_HASH = "0" * 64


def coordinates(**changes: object) -> SchedulerInput:
    values: dict[str, object] = {
        "scenario_hash": ZERO_HASH,
        "input_resource_hashes": {},
        "run_index": 0,
        "schedule_seed": 0,
        "selection_ordinal": 0,
        "committed_history_length": 0,
        "logical_clock": CLOCK,
        "declared_actors": (A,),
        "ready_actors": (A,),
    }
    values.update(changes)
    return SchedulerInput(**values)  # type: ignore[arg-type]


def test_independent_golden_one_actor_computes_complete_digest() -> None:
    decision = select_actor(coordinates())
    expected = (
        b'{"contract":"scenario.scheduler/1","coordinates":{"committed_history_length":0,'
        b'"input_resource_hashes":{},"logical_clock":{"$type":"datetime","value":'
        b'"2026-01-01T00:00:00.000000+00:00"},"ready_actors":["scenario:/actor/alpha"],'
        b'"run_index":0,"scenario_hash":"' + b"0" * 64 +
        b'","schedule_seed":0,"selection_ordinal":0}}'
    )
    assert decision.contract == SCHEDULER_CONTRACT
    assert decision.canonical_bytes == expected
    assert decision.digest == "db753de068e327a09694ccd0b4676a0c602fe9c5380f7e185a0835a1b194bc66"
    assert (decision.selected_index, decision.selected_actor) == (0, A)


def test_independent_golden_two_actor_seed_and_resource_identity() -> None:
    decision = select_actor(coordinates(
        input_resource_hashes={"input:user": "a" * 64}, schedule_seed=1,
        declared_actors=(B, A), ready_actors=(B, A),
    ))
    assert decision.digest == "d14c771920e3d451645bfd62d9458225c667ae824ab838516ae5abab4b19585d"
    assert (decision.selected_index, decision.selected_actor) == (1, B)
    assert decision.ready_actors == (A, B)


def test_independent_golden_three_actor_unicode_ordinal_and_reordering() -> None:
    arguments = dict(
        scenario_hash="f" * 64, run_index=7, selection_ordinal=1,
        committed_history_length=1,
        logical_clock=datetime(2026, 1, 1, 0, 0, 1, 2, tzinfo=timezone.utc),
        declared_actors=(B, U, A),
    )
    first = select_actor(coordinates(**arguments, ready_actors=(U, A, B)))
    second = select_actor(coordinates(**arguments, ready_actors=(B, U, A)))
    assert first == second
    assert first.digest == "3abc028519a8d1dd300fec26e33744182198e8f871cadbff138c75f699cca87b"
    assert (first.selected_index, first.selected_actor) == (1, A)


@pytest.mark.parametrize(("field_name", "value"), [
    ("run_index", True), ("run_index", -1), ("schedule_seed", False),
    ("schedule_seed", -1), ("schedule_seed", 1.0), ("schedule_seed", "1"),
    ("schedule_seed", MAX_SCHEDULE_SEED + 1), ("selection_ordinal", True),
    ("selection_ordinal", -1), ("selection_ordinal", MAX_SELECTION_ORDINAL + 1),
    ("committed_history_length", True), ("committed_history_length", -1),
])
def test_invalid_integer_coordinates_fail_closed(field_name: str, value: object) -> None:
    with pytest.raises(SchedulerValidationError, match=field_name):
        coordinates(**{field_name: value})


def test_inclusive_seed_and_selection_ordinal_boundaries_are_accepted() -> None:
    item = coordinates(schedule_seed=MAX_SCHEDULE_SEED, selection_ordinal=MAX_SELECTION_ORDINAL)
    assert item.schedule_seed == MAX_SCHEDULE_SEED
    assert item.selection_ordinal == MAX_SELECTION_ORDINAL


@pytest.mark.parametrize("value", ["F" * 64, "0" * 63, "g" * 64, 0, None])
def test_scenario_hash_must_be_canonical(value: object) -> None:
    with pytest.raises(SchedulerValidationError, match="scenario_hash"):
        coordinates(scenario_hash=value)


def test_actor_membership_uniqueness_canonicality_and_empty_ready_set() -> None:
    with pytest.raises(SchedulerValidationError, match="must not be empty"):
        coordinates(ready_actors=())
    with pytest.raises(SchedulerValidationError, match="duplicates"):
        coordinates(declared_actors=(A, A))
    with pytest.raises(SchedulerValidationError, match="not declared"):
        coordinates(ready_actors=(B,))
    with pytest.raises(SchedulerValidationError, match="not canonical"):
        coordinates(declared_actors=("scenario:/actor/%c3%a9clair",))


def test_clock_and_manifest_resource_mapping_semantic_types_fail_closed() -> None:
    with pytest.raises(SchedulerValidationError, match="logical_clock"):
        coordinates(logical_clock=datetime(2026, 1, 1))
    with pytest.raises(SchedulerValidationError, match="input_resource_hashes"):
        coordinates(input_resource_hashes={1: "digest"})
    with pytest.raises(SchedulerValidationError, match="input_resource_hashes"):
        coordinates(input_resource_hashes={"input:x": 1})


def test_inputs_and_result_are_immutable_and_input_mapping_is_copied() -> None:
    resources = {"input:x": "digest"}
    item = coordinates(input_resource_hashes=resources)
    resources["input:x"] = "changed"
    assert item.input_resource_hashes["input:x"] == "digest"
    with pytest.raises(TypeError):
        item.input_resource_hashes["x"] = "y"  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        select_actor(item).selected_index = 1  # type: ignore[misc]


def test_cross_process_and_python_hash_seed_outputs_are_byte_identical() -> None:
    code = (
        "from datetime import datetime,timezone; from scenario_engine.scheduler import *; "
        f"x=SchedulerInput('{ZERO_HASH}',{{}},0,0,0,0,datetime(2026,1,1,tzinfo=timezone.utc),"
        f"({A!r},{B!r}),({B!r},{A!r})); d=select_actor(x); "
        "print(json.dumps({'bytes':d.canonical_bytes.hex(),'digest':d.digest,'actor':d.selected_actor},sort_keys=True))"
    )
    code = "import json; " + code
    outputs = []
    for seed in ("1", "987654"):
        environment = os.environ.copy()
        environment.update({"PYTHONHASHSEED": seed, "PYTHONPATH": str(ROOT / "src")})
        outputs.append(subprocess.check_output([sys.executable, "-c", code], cwd=ROOT, env=environment))
    assert outputs[0] == outputs[1]
    assert json.loads(outputs[0])["digest"]
