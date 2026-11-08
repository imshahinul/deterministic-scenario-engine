from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import os
from pathlib import Path
import subprocess
import sys
from time import monotonic

import pytest

from scenario_engine.engine2 import ResultFailure, construct_result2, validate_engine2
import scenario_engine.engine2_input_shrink as shrink
from scenario_engine.engine2_input_shrink import (
    Engine2InputShrinkError, Engine2InputShrinkOutcome, Engine2InputShrinkRequest,
    shrink_failed_inputs,
)
from scenario_engine.invariants import InvariantViolation
from scenario_engine.values import canonical_bytes


ROOT = Path(__file__).parents[1]
SOURCE = """dsl_version: 2
scenario: input-preserve
clock: {start: '2026-01-01T00:00:00Z'}
initial_state: {value: 0}
resources:
  cfg: {$input: cfg}
actors:
  - id: target
    steps:
      - id: fail
        write: {value: {$literal: 1}}
        transition: null
invariants:
  - id: stays-zero
    check: {$lte: [{$state: value}, {$literal: 0}]}
"""


def evidence(source=SOURCE, inputs=None):
    inputs = {"cfg": {"unused": [9, 8, 7]}} if inputs is None else inputs
    scenario = validate_engine2(source)
    from scenario_engine.engine2 import execute_engine2
    for seed in range(200):
        try:
            execute_engine2(scenario, "root", seed, run_index=2, inputs=inputs)
        except InvariantViolation as error:
            result = construct_result2(scenario, error.internal_outcome)
            if result.failure.actor == "scenario:/actor/target":
                return result, error.internal_outcome.schedule, seed
    raise AssertionError("no bounded failing seed")


def request(inputs=None, source=SOURCE, **changes):
    inputs = {"cfg": {"unused": [9, 8, 7]}} if inputs is None else inputs
    result = changes.pop("result", None)
    schedule = changes.pop("schedule", None)
    seed = changes.pop("schedule_seed", None)
    if result is None or schedule is None or seed is None:
        result, schedule, seed = evidence(source, inputs)
    values = dict(
        source=source, result=result, schedule=schedule, root_seed="root",
        schedule_seed=seed, run_index=2, inputs=inputs, eligible_input_paths=None,
        max_candidate_evaluations=64, total_execution_budget=128,
        repetition_count=3, deadline=monotonic() + 120,
    )
    values.update(changes)
    return Engine2InputShrinkRequest(**values)


def stable(outcome):
    return (outcome.status, outcome.stop_reason, outcome.original_input_size,
            outcome.reduced_input_size, outcome.removed, outcome.candidate_evaluations,
            outcome.execution_count, outcome.accepted_count, outcome.rejected_count,
            outcome.invalid_count, outcome.final_result_hash, outcome.final_schedule_hash,
            outcome.minimality)


def test_shr4_collection_26_to_21_and_native_replay() -> None:
    item = request()
    outcome = shrink_failed_inputs(item)
    assert (outcome.original_input_size, outcome.reduced_input_size) == (26, 21)
    assert outcome.reduced_inputs == {"cfg": {"unused": ()}}
    assert outcome.removed == (
        (("cfg", "unused"), 0), (("cfg", "unused"), 1), (("cfg", "unused"), 2),
    )
    assert outcome.final_result.classification == "FAILED"
    assert outcome.failure_identity == {
        "actor": "scenario:/actor/target", "code": "InvariantViolation",
        "invariant_expression": {"$lte": ({"$state": "value"}, {"$literal": 0})},
        "invariant_id": "stays-zero", "selection_ordinal": 0, "step_id": "fail",
    }
    assert outcome.determinism_verified and outcome.replay_verified
    assert outcome.minimality == "1_MINIMAL_UNDER_ELIGIBLE_LIST_DELETIONS"
    assert item.source == SOURCE


@pytest.mark.parametrize("items", [[1], [1, 2, 3, 4]])
def test_one_and_multiple_element_reduction_preserves_order(items) -> None:
    outcome = shrink_failed_inputs(request({"cfg": {"unused": items}}))
    assert outcome.status == "REDUCED"
    assert outcome.reduced_inputs["cfg"]["unused"] == ()
    assert outcome.accepted_count == len(items)


def test_nested_lists_are_reduced_in_canonical_path_order() -> None:
    inputs = {"cfg": {"z": [3], "a": {"inner": [1, 2]}}}
    outcome = shrink_failed_inputs(request(inputs))
    assert outcome.reduced_inputs == {"cfg": {"a": {"inner": ()}, "z": ()}}
    assert tuple(path for path, _ in outcome.removed) == (
        ("cfg", "a", "inner"), ("cfg", "a", "inner"), ("cfg", "z"),
    )


def test_nested_list_path_does_not_retarget_after_ancestor_deletion() -> None:
    inputs = {"cfg": {"outer": [{"inner": [1]}, {"inner": [2]}]}}
    item = request(inputs, eligible_input_paths=(
        ("cfg", "outer"), ("cfg", "outer", 0, "inner"),
        ("cfg", "outer", 1, "inner"),
    ))
    outcome = shrink_failed_inputs(item)
    assert outcome.reduced_inputs == {"cfg": {"outer": ()}}
    # Once original outer[0] is deleted, its frozen nested path is invalid;
    # it must never be redirected to the original outer[1] element.
    assert (("cfg", "outer", 0, "inner"), 0) not in outcome.removed


def test_retained_order_and_strict_size_metric() -> None:
    inputs = {"cfg": {"values": [1, 0, -1]}}
    outcome = shrink_failed_inputs(request(inputs, max_candidate_evaluations=1))
    assert outcome.original_input_size > outcome.reduced_input_size
    assert tuple(outcome.reduced_inputs["cfg"]["values"]) == (0, -1)
    assert outcome.failure_identity["actor"] == "scenario:/actor/target"


def test_honest_no_reduction_for_empty_and_no_eligible_lists() -> None:
    for inputs in ({"cfg": {"unused": []}}, {"cfg": {"unused": "scalar"}}):
        outcome = shrink_failed_inputs(request(inputs))
        assert outcome.status == "NO_REDUCTION"
        assert outcome.original_input_size == outcome.reduced_input_size
        assert outcome.complete_final_pass


def test_only_consumed_input_roots_are_eligible() -> None:
    inputs = {"cfg": {"unused": []}, "secret": [1, 2, 3]}
    outcome = shrink_failed_inputs(request(inputs))
    assert outcome.eligible_input_paths == (("cfg", "unused"),)
    assert outcome.reduced_inputs["secret"] == (1, 2, 3)
    assert outcome.original_input_size == outcome.reduced_input_size


def test_nested_consumed_path_excludes_unrelated_sibling_list() -> None:
    source = SOURCE.replace("cfg: {$input: cfg}", "cfg: {$input: cfg.used}")
    inputs = {"cfg": {"used": {"items": [1, 2]}, "sibling": [3, 4]}}
    outcome = shrink_failed_inputs(request(inputs, source))
    assert outcome.eligible_input_paths == (("cfg", "used", "items"),)
    assert outcome.reduced_inputs == {
        "cfg": {"sibling": (3, 4), "used": {"items": ()}},
    }


def test_nested_list_declaration_and_multiple_consumed_paths_are_exact() -> None:
    source = SOURCE.replace(
        "cfg: {$input: cfg}",
        "first: {$input: cfg.first}\n  second: {$input: cfg.container.items}",
    )
    inputs = {"cfg": {"first": [1], "container": {"items": [2, 3], "other": [4]}}}
    outcome = shrink_failed_inputs(request(inputs, source))
    assert outcome.eligible_input_paths == (
        ("cfg", "container", "items"), ("cfg", "first"),
    )
    assert outcome.reduced_inputs["cfg"]["container"]["other"] == (4,)


def test_overlapping_parent_child_declarations_do_not_duplicate_paths() -> None:
    source = SOURCE.replace(
        "cfg: {$input: cfg}",
        "whole: {$input: cfg}\n  child: {$input: cfg.used}",
    )
    outcome = shrink_failed_inputs(request({"cfg": {"used": [1], "sibling": [2]}}, source))
    assert outcome.eligible_input_paths == (("cfg", "sibling"), ("cfg", "used"))
    assert outcome.accepted_count == 2


def test_missing_required_nested_input_is_not_eligible_or_executed() -> None:
    source = SOURCE.replace("cfg: {$input: cfg}", "cfg: {$input: cfg.required.items}")
    valid = request({"cfg": {"required": {"items": [1]}}}, source)
    outcome = shrink_failed_inputs(replace(valid, inputs={"cfg": {"sibling": [1]}}))
    assert outcome.stop_reason == "INPUTS_OR_RESOURCES_INVALID"
    assert outcome.candidate_evaluations == 0


def test_explicit_invalid_or_unconsumed_path_rejected_before_speculation() -> None:
    item = request({"cfg": {"unused": [1]}, "secret": [2]})
    for path in (("cfg", "missing"), ("secret",)):
        outcome = shrink_failed_inputs(replace(item, eligible_input_paths=(path,)))
        assert outcome.status == "REJECTED"
        assert outcome.stop_reason == "ELIGIBLE_INPUT_PATH_INVALID_OR_UNCONSUMED"
        assert outcome.candidate_evaluations == 0


@pytest.mark.parametrize("field,value", [
    ("max_candidate_evaluations", 0), ("max_candidate_evaluations", 65),
    ("max_candidate_evaluations", True), ("total_execution_budget", 0),
    ("total_execution_budget", 129), ("total_execution_budget", True),
    ("repetition_count", 2), ("repetition_count", True),
])
def test_strict_bounds_and_boolean_integer_rejection(field, value) -> None:
    with pytest.raises(Engine2InputShrinkError):
        request(**{field: value})


def test_execution_budget_and_deadline_never_claim_minimality() -> None:
    budget = shrink_failed_inputs(request(total_execution_budget=4))
    assert budget.stop_reason == "TOTAL_EXECUTION_BUDGET_EXHAUSTED"
    assert budget.execution_count == 4
    assert budget.minimality == "MINIMALITY_NOT_ESTABLISHED"
    deadline = shrink_failed_inputs(request(deadline=monotonic() - 1))
    assert deadline.stop_reason == "DEADLINE_REACHED"
    assert deadline.execution_count == 0
    assert deadline.minimality == "MINIMALITY_NOT_ESTABLISHED"


def test_evaluation_budget_is_distinct_from_execution_count() -> None:
    outcome = shrink_failed_inputs(request(max_candidate_evaluations=1))
    assert outcome.candidate_evaluations == 1
    assert outcome.execution_count == 8  # baseline replay/reruns + candidate reruns/replay
    assert outcome.minimality == "MINIMALITY_NOT_ESTABLISHED"


def test_resource_resolution_failure_is_invalid_before_execution(monkeypatch) -> None:
    item = request({"cfg": {"required": [1]}})
    real_resolve = shrink.resolve_resources
    original_size = len(canonical_bytes(item.inputs))
    def reject_candidate(declarations, inputs):
        if len(canonical_bytes(inputs)) < original_size:
            raise ValueError("redacted fixture rejection")
        return real_resolve(declarations, inputs)
    monkeypatch.setattr(shrink, "resolve_resources", reject_candidate)
    outcome = shrink_failed_inputs(item)
    assert outcome.invalid_count == 1
    assert "RESOURCE_RESOLUTION_FAILED" in outcome.rejection_reasons
    assert outcome.status == "NO_REDUCTION"


def test_changed_source_coordinates_and_malformed_evidence_rejected() -> None:
    item = request()
    changed = item.source.replace("scenario: input-preserve", "scenario: changed")
    assert shrink_failed_inputs(replace(item, source=changed)).stop_reason == "EVIDENCE_COORDINATES_OR_LINKAGE_MISMATCH"
    assert shrink_failed_inputs(replace(item, result=b"{}")).stop_reason == "BASELINE_MALFORMED_OR_INVALID"
    assert shrink_failed_inputs(replace(item, schedule=b"{}")).stop_reason == "BASELINE_MALFORMED_OR_INVALID"


def test_input_coordinate_mismatch_and_error_without_failed_evidence_rejected() -> None:
    item = request()
    assert shrink_failed_inputs(replace(item, inputs={"cfg": {"unused": [0]}})).stop_reason == "RESOURCE_COORDINATES_MISMATCH"
    success_source = SOURCE.replace("{$literal: 1}", "{$literal: 0}")
    scenario = validate_engine2(success_source)
    from scenario_engine.engine2 import execute_engine2
    result, schedule = execute_engine2(scenario, "root", 0, run_index=2,
                                       inputs={"cfg": {"unused": [1]}})
    outcome = shrink_failed_inputs(request(
        {"cfg": {"unused": [1]}}, success_source, result=result,
        schedule=schedule, schedule_seed=0,
    ))
    assert outcome.stop_reason == "NATIVE_FAILED_INVARIANT_VIOLATION_REQUIRED"


def test_plugin_scenario_rejected_without_plugin_execution() -> None:
    source = SOURCE.replace(
        "write: {value: {$literal: 1}}",
        "generate: {x: {$plugin: {name: forbidden, version: '1'}}}\n        write: {value: {$literal: 1}}",
    )
    item = request()
    outcome = shrink_failed_inputs(replace(item, source=source))
    assert outcome.stop_reason == "PLUGINS_UNSUPPORTED"
    assert outcome.execution_count == 0


@pytest.mark.parametrize("change", ["actor", "ordinal", "step", "invariant"])
def test_different_actor_ordinal_step_and_invariant_are_rejected(monkeypatch, change) -> None:
    item = request()
    baseline_size = len(canonical_bytes(item.inputs))
    real_run = shrink._run

    def altered(scenario, supplied, inputs, budget):
        run = real_run(scenario, supplied, inputs, budget)
        if run is not None and len(canonical_bytes(inputs)) < baseline_size:
            if change == "step":
                return replace(run, step_id="different-step")
            if change == "invariant":
                return replace(run, invariant_id="different-invariant")
            assert run.result.failure is not None
            failure = ResultFailure(
                "scenario:/actor/other" if change == "actor" else run.result.failure.actor,
                run.result.failure.code,
                1 if change == "ordinal" else run.result.failure.selection_ordinal,
            )
            return replace(run, result=replace(run.result, failure=failure, result_hash=""))
        return run

    monkeypatch.setattr(shrink, "_run", altered)
    outcome = shrink_failed_inputs(item)
    assert outcome.status == "NO_REDUCTION"
    assert outcome.rejected_count == 3
    assert all(reason == "FAILURE_SIGNATURE_OR_DETERMINISM_MISMATCH"
               for reason in outcome.rejection_reasons)


def test_genuine_native_different_actor_candidate_returns_no_reduction() -> None:
    source = SOURCE.replace(
        "invariants:\n",
        "  - id: z-alt\n"
        "    steps:\n"
        "      - id: fail-alt\n"
        "        write: {value: {$literal: 1}}\n"
        "        transition: null\n"
        "invariants:\n",
    )
    scenario = validate_engine2(source)
    from scenario_engine.engine2 import execute_engine2

    def native_failure(inputs, seed):
        try:
            execute_engine2(scenario, "root", seed, run_index=2, inputs=inputs)
        except InvariantViolation as error:
            return construct_result2(scenario, error.internal_outcome), error.internal_outcome.schedule
        raise AssertionError("expected native invariant failure")

    original_inputs = {"cfg": {"unused": [1]}}
    candidate_inputs = {"cfg": {"unused": []}}
    for seed in range(200):
        result, schedule = native_failure(original_inputs, seed)
        candidate_result, _ = native_failure(candidate_inputs, seed)
        if (result.failure.actor == "scenario:/actor/target"
                and candidate_result.failure.actor == "scenario:/actor/z-alt"):
            break
    else:
        raise AssertionError("no bounded native different-actor coordinate")

    outcome = shrink_failed_inputs(request(
        original_inputs, source, result=result, schedule=schedule,
        schedule_seed=seed, max_candidate_evaluations=1,
    ))
    assert outcome.status == "NO_REDUCTION"
    assert outcome.candidate_evaluations == 1
    assert outcome.accepted_count == 0
    assert outcome.rejected_count == 1
    assert outcome.rejection_reasons == ("FAILURE_SIGNATURE_OR_DETERMINISM_MISMATCH",)


def test_candidate_nondeterminism_and_no_replay_evidence_rejected(monkeypatch) -> None:
    item = request()
    baseline_size = len(canonical_bytes(item.inputs))
    calls = 0
    real_run = shrink._run

    def nondeterministic(scenario, supplied, inputs, budget):
        nonlocal calls
        run = real_run(scenario, supplied, inputs, budget)
        if run is not None and len(canonical_bytes(inputs)) < baseline_size:
            calls += 1
            if calls % 3 == 0:
                return replace(run, invariant_id="changed")
        return run

    monkeypatch.setattr(shrink, "_run", nondeterministic)
    assert shrink_failed_inputs(item).status == "NO_REDUCTION"

    monkeypatch.setattr(shrink, "_run", real_run)
    real_replay = shrink._replay
    def no_candidate_replay(run, scenario, inputs, budget):
        if len(canonical_bytes(inputs)) < baseline_size:
            budget.take()
            return False
        return real_replay(run, scenario, inputs, budget)
    monkeypatch.setattr(shrink, "_replay", no_candidate_replay)
    outcome = shrink_failed_inputs(item)
    assert outcome.status == "NO_REDUCTION"
    assert "CANDIDATE_EXACT_REPLAY_FAILED" in outcome.rejection_reasons


def test_cycle_alias_tuple_custom_mapping_and_oversize_are_rejected() -> None:
    valid = request()
    cyclic = {"cfg": []}; cyclic["cfg"].append(cyclic)
    shared = [1]; aliased = {"cfg": {"a": shared, "b": shared}}
    class Evil(dict):
        pass
    for inputs in (cyclic, aliased, {"cfg": (1, 2)}, Evil(cfg=[1])):
        with pytest.raises(Engine2InputShrinkError):
            Engine2InputShrinkRequest(
                valid.source, valid.result, valid.schedule, valid.root_seed,
                valid.schedule_seed, valid.run_index, inputs, None, 64, 128, 3,
                monotonic() + 10,
            )
    with pytest.raises(Engine2InputShrinkError, match="bounded canonical input size"):
        Engine2InputShrinkRequest(
            valid.source, valid.result, valid.schedule, valid.root_seed,
            valid.schedule_seed, valid.run_index, {"cfg": ["x" * 262_144]},
            None, 64, 128, 3, monotonic() + 10,
        )


def test_original_and_returned_inputs_are_defensive_and_secret_safe() -> None:
    inputs = {"cfg": {"secret-value": [9, 8]}}
    item = request(inputs)
    inputs["cfg"]["secret-value"].append(7)
    outcome = shrink_failed_inputs(item)
    assert tuple(item.inputs["cfg"]["secret-value"]) == (9, 8)
    assert "secret-value" not in repr(item)
    assert "secret-value" not in repr(outcome)
    with pytest.raises(TypeError):
        outcome.reduced_inputs["cfg"]["secret-value"] = ()
    with pytest.raises(AttributeError):
        outcome.reduced_inputs["cfg"]["secret-value"].append(1)
    with pytest.raises(FrozenInstanceError):
        outcome.status = "changed"


def test_direct_outcome_construction_recursively_snapshots_mutable_fields() -> None:
    original = {"cfg": {"items": [1, 2]}}
    reduced = {"cfg": {"items": [2]}}
    removed = [(["cfg", "items"], 0)]
    paths = [["cfg", "items"]]
    coordinates = {"seed": {"parts": ["fixed"]}}
    identity = {"expression": {"args": [1, 2]}}
    outcome = Engine2InputShrinkOutcome(
        "REDUCED", "NO_FURTHER_ACCEPTABLE_DELETION",
        len(canonical_bytes(original)), len(canonical_bytes(reduced)),
        original, reduced, removed, paths, coordinates, identity,
        None, None, None, None, None, None,
    )
    original["cfg"]["items"].append(3)
    reduced["cfg"]["items"].clear()
    removed[0][0].append("retarget")
    paths[0].append("retarget")
    coordinates["seed"]["parts"].append("changed")
    identity["expression"]["args"].append(3)
    assert outcome.original_inputs == {"cfg": {"items": (1, 2)}}
    assert outcome.reduced_inputs == {"cfg": {"items": (2,)}}
    assert outcome.removed == ((('cfg', 'items'), 0),)
    assert outcome.eligible_input_paths == (("cfg", "items"),)
    assert outcome.coordinates == {"seed": {"parts": ("fixed",)}}
    assert outcome.failure_identity == {"expression": {"args": (1, 2)}}
    with pytest.raises(TypeError):
        outcome.failure_identity["expression"]["args"] = ()
    with pytest.raises(AttributeError):
        outcome.coordinates["seed"]["parts"].append("x")


def test_direct_outcome_rejects_inconsistent_snapshot_sizes_without_value_leak() -> None:
    secret = {"cfg": {"do-not-print": [1]}}
    with pytest.raises(Engine2InputShrinkError) as captured:
        Engine2InputShrinkOutcome(
            "NO_REDUCTION", "TEST", 0, len(canonical_bytes(secret)),
            secret, secret, (), (), {}, {}, None, None, None, None, None, None,
        )
    assert "do-not-print" not in str(captured.value)


def test_cross_process_hashseed_stability() -> None:
    code = f'''from time import monotonic
from scenario_engine.engine2 import validate_engine2,execute_engine2,construct_result2
from scenario_engine.engine2_input_shrink import *
from scenario_engine.invariants import InvariantViolation
s={SOURCE!r};i={{"cfg":{{"unused":[9,8,7]}}}};c=validate_engine2(s)
for seed in range(200):
 try: execute_engine2(c,"root",seed,run_index=2,inputs=i)
 except InvariantViolation as e: r=construct_result2(c,e.internal_outcome);q=e.internal_outcome.schedule;break
x=shrink_failed_inputs(Engine2InputShrinkRequest(s,r,q,"root",seed,2,i,None,64,128,3,monotonic()+60))
print(repr((x.status,x.stop_reason,x.removed,x.original_input_size,x.reduced_input_size,x.candidate_evaluations,x.execution_count,x.final_result_hash,x.final_schedule_hash,x.minimality)))'''
    outputs = []
    for seed in ("1", "777"):
        env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONHASHSEED": seed,
               "PYTHONDONTWRITEBYTECODE": "1"}
        outputs.append(subprocess.check_output([sys.executable, "-c", code], cwd=ROOT, env=env))
    assert outputs[0] == outputs[1]


def test_no_package_root_export_or_existing_contract_mutation() -> None:
    import scenario_engine
    assert not hasattr(scenario_engine, "shrink_failed_inputs")
    outcome = shrink_failed_inputs(request())
    assert outcome.final_result.contract == "scenario.result/2"
    assert outcome.final_schedule.contract == "scenario.schedule/1"


def test_documented_installed_consumer_example_is_executable() -> None:
    text = (ROOT / "docs/engine2-input-shrink.md").read_text(encoding="utf-8")
    marked = text.split("<!-- installed-consumer-example:start -->", 1)[1].split(
        "<!-- installed-consumer-example:end -->", 1,
    )[0]
    example = marked.split("```python\n", 1)[1].rsplit("```", 1)[0]
    exec(compile(example, "docs/engine2-input-shrink.md", "exec"), {})
