from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import json
import os
from pathlib import Path
import subprocess
import sys
from time import monotonic

import pytest

from scenario_engine.engine2 import (
    ResultFailure, canonical_result2_bytes, construct_result2, validate_engine2,
)
import scenario_engine.engine2_shrink as engine2_shrink
from scenario_engine.engine2_shrink import (
    FAILURE_PRESERVATION_LEVEL, MAX_CANDIDATE_EVALUATIONS, Engine2ShrinkError,
    Engine2ShrinkRequest, shrink_failed_scenario,
)
from scenario_engine.invariants import InvariantViolation
from scenario_engine.schedule import canonical_schedule_bytes


ROOT = Path(__file__).parents[1]


def source(noise=("z-noise",), *, invariant=None, target_write=1, plugin=False) -> str:
    invariant = invariant or "{$lte: [{$state: value}, {$literal: 0}]}"
    actors = [
        "  - id: target\n    steps:\n      - id: fail\n"
        + ("        generate: {x: {$plugin: {name: x, version: '1'}}}\n" if plugin else "")
        + f"        write: {{value: {{$literal: {target_write}}}}}\n        transition: null\n"
    ]
    actors.extend(
        f"  - id: {name}\n    steps:\n      - id: idle\n"
        "        write: {value: {$state: value}}\n        transition: null\n"
        for name in noise
    )
    return (
        "dsl_version: 2\nscenario: shrink-case\n"
        "clock: {start: '2026-01-01T00:00:00Z'}\n"
        "initial_state: {value: 0}\nactors:\n" + "".join(actors)
        + "invariants:\n  - id: stays-zero\n    check: " + invariant + "\n"
    )


def failed_evidence(text: str, *, root="root", run_index=2):
    scenario = validate_engine2(text)
    for seed in range(200):
        try:
            from scenario_engine.engine2 import execute_engine2
            execute_engine2(scenario, root, seed, run_index=run_index)
        except InvariantViolation as error:
            outcome = error.internal_outcome
            result = construct_result2(scenario, outcome)
            if result.failure.actor == "scenario:/actor/target" and result.failure.selection_ordinal == 0:
                return result, outcome.schedule, seed
    raise AssertionError("fixture could not find a bounded target-first schedule seed")


def request(text=None, **changes):
    text = source() if text is None else text
    supplied_result = changes.pop("result", None)
    supplied_schedule = changes.pop("schedule", None)
    supplied_seed = changes.pop("schedule_seed", None)
    if supplied_result is None or supplied_schedule is None or supplied_seed is None:
        result, schedule, seed = failed_evidence(text)
    else:
        result, schedule, seed = supplied_result, supplied_schedule, supplied_seed
    values = dict(
        source=text, result=result, schedule=schedule, root_seed="root",
        schedule_seed=seed, run_index=2, inputs=None, max_candidate_evaluations=64,
        total_execution_budget=300,
        deadline=monotonic() + 300, repetition_count=3,
    )
    values.update(changes)
    return Engine2ShrinkRequest(**values)


def summary(outcome):
    return {
        "status": outcome.status, "reason": outcome.reason,
        "removed": outcome.removed_actor_addresses,
        "counts": dict(outcome.reduced_counts), "evaluations": outcome.candidate_evaluations,
        "executions": outcome.execution_count, "accepted": outcome.accepted_count,
        "rejected": outcome.rejected_count, "invalid": outcome.invalid_count,
        "minimality": outcome.minimality, "result": outcome.final_result_hash,
        "schedule": outcome.final_schedule_hash, "scenario": outcome.final_scenario_hash,
    }


def test_remove_one_never_selected_actor_and_preserve_failure() -> None:
    outcome = shrink_failed_scenario(request())
    assert outcome.status == "REDUCED"
    assert outcome.removed_actor_addresses == ("scenario:/actor/z-noise",)
    assert outcome.reduced_counts["actors"] == 1
    assert outcome.final_result.classification == "FAILED"
    assert outcome.final_result.failure.code == "InvariantViolation"
    assert outcome.final_result.failure.actor == "scenario:/actor/target"
    assert outcome.final_result.failure.selection_ordinal == 0
    assert outcome.preservation_level == FAILURE_PRESERVATION_LEVEL
    assert outcome.replay_verified and outcome.determinism_verified


def test_remove_multiple_in_canonical_order_and_preserve_declared_retained_order() -> None:
    text = source(("z-noise", "a-noise", "m-noise"))
    variants = (
        text,
        source(("z-noise", "m-noise")),
        source(("z-noise",)),
        source(()),
    )
    compiled = tuple(validate_engine2(item) for item in variants)
    from scenario_engine.engine2 import execute_engine2
    for seed in range(10_000):
        failures = []
        for scenario in compiled:
            try:
                execute_engine2(scenario, "root", seed, run_index=2)
            except InvariantViolation as error:
                failures.append(error)
        if (len(failures) == len(compiled)
                and all(error.internal_outcome.schedule.failure.actor == "scenario:/actor/target"
                        and error.internal_outcome.schedule.failure.selection_ordinal == 0
                        for error in failures)):
            break
    else:
        raise AssertionError("no bounded multi-removal fixture seed")
    result = construct_result2(compiled[0], failures[0].internal_outcome)
    outcome = shrink_failed_scenario(request(
        text, result=result, schedule=failures[0].internal_outcome.schedule,
        schedule_seed=seed,
    ))
    assert outcome.removed_actor_addresses == (
        "scenario:/actor/a-noise", "scenario:/actor/m-noise", "scenario:/actor/z-noise",
    )
    assert outcome.reduced_source.index("id: target") < outcome.reduced_source.index("invariants:")
    assert outcome.minimality == "1_MINIMAL_UNDER_ELIGIBLE_ACTOR_DELETION"


def test_invariant_id_expression_and_target_actor_are_unchanged() -> None:
    item = request(source(("z-noise", "a-noise")))
    outcome = shrink_failed_scenario(item)
    original = validate_engine2(item.source)
    reduced = validate_engine2(outcome.reduced_source)
    assert reduced.document.invariants == original.document.invariants
    target = lambda scenario: next(a for a in scenario.document.actors if a.address.endswith("/target"))
    assert target(reduced) == target(original)
    assert outcome.failure_identity["invariant_id"] == "stays-zero"


def test_nested_failure_identity_is_defensively_frozen_without_native_change(monkeypatch) -> None:
    item = request(source(("z-noise", "a-noise")))
    parsed = []
    validate = engine2_shrink.validate_engine2

    def capture(text):
        scenario = validate(text)
        parsed.append(scenario)
        return scenario

    monkeypatch.setattr(engine2_shrink, "validate_engine2", capture)
    outcome = shrink_failed_scenario(item)
    expression = outcome.failure_identity["invariant_expression"]
    original_expression = parsed[0].document.invariants[0]["check"]
    original_snapshot = json.dumps(original_expression, sort_keys=True)
    result_bytes = canonical_result2_bytes(outcome.final_result)
    schedule_bytes = canonical_schedule_bytes(outcome.final_schedule)

    assert expression == {
        "$lte": ({"$state": "value"}, {"$literal": 0}),
    }
    assert expression is not original_expression
    assert expression["$lte"] is not original_expression["$lte"]
    with pytest.raises(FrozenInstanceError):
        outcome.failure_identity = {}  # type: ignore[misc]
    with pytest.raises(TypeError):
        outcome.failure_identity["actor"] = "changed"  # type: ignore[index]
    with pytest.raises(TypeError):
        expression["$lte"] = ()  # type: ignore[index]
    with pytest.raises(TypeError):
        expression["$lte"][0]["$state"] = "changed"  # type: ignore[index]
    with pytest.raises(AttributeError):
        expression["$lte"].append({"$literal": 1})

    assert json.dumps(original_expression, sort_keys=True) == original_snapshot
    assert canonical_result2_bytes(outcome.final_result) == result_bytes
    assert canonical_schedule_bytes(outcome.final_schedule) == schedule_bytes


def test_repeated_nested_failure_summaries_are_identical() -> None:
    item = request(source(("z-noise", "a-noise")))
    first, second = shrink_failed_scenario(item), shrink_failed_scenario(item)
    assert first.failure_identity == second.failure_identity
    assert repr(first.failure_identity) == repr(second.failure_identity)
    assert first.failure_identity["invariant_expression"]["$lte"] == (
        {"$state": "value"}, {"$literal": 0},
    )


def test_deterministic_no_reduction_and_identical_output() -> None:
    text = source(())
    item = request(text)
    one = shrink_failed_scenario(item)
    two = shrink_failed_scenario(item)
    assert one.status == two.status == "NO_REDUCTION"
    assert one.reduced_source == two.reduced_source == text
    assert summary(one) == summary(two)
    assert canonical_result2_bytes(one.final_result) == canonical_result2_bytes(item.result)
    assert canonical_schedule_bytes(one.final_schedule) == canonical_schedule_bytes(item.schedule)


@pytest.mark.parametrize("field,value", [
    ("max_candidate_evaluations", 0), ("max_candidate_evaluations", 65),
    ("max_candidate_evaluations", True), ("repetition_count", 2),
    ("repetition_count", True), ("total_execution_budget", 0),
])
def test_strict_numeric_bounds(field, value) -> None:
    with pytest.raises(Engine2ShrinkError):
        request(**{field: value})


def test_maximum_evaluation_budget_is_accepted() -> None:
    assert request(max_candidate_evaluations=MAX_CANDIDATE_EVALUATIONS)


def test_deadline_exhaustion_is_honest() -> None:
    outcome = shrink_failed_scenario(request(
        deadline=monotonic() - 1,
    ))
    assert outcome.status == "REJECTED" and outcome.reason == "DEADLINE_REACHED"
    assert outcome.minimality == "MINIMALITY_NOT_ESTABLISHED"


def test_total_execution_exhaustion_and_no_fake_minimality() -> None:
    outcome = shrink_failed_scenario(request(total_execution_budget=4))
    assert outcome.status == "NO_REDUCTION"
    assert outcome.reason == "TOTAL_EXECUTION_BUDGET_EXHAUSTED"
    assert outcome.minimality == "MINIMALITY_NOT_ESTABLISHED"


def test_evaluation_exhaustion_after_acceptance_is_honest() -> None:
    outcome = shrink_failed_scenario(request(
        source(("a-noise", "z-noise")), max_candidate_evaluations=1,
    ))
    assert outcome.status == "REDUCED" and outcome.accepted_count == 1
    assert outcome.reason == "EVALUATION_BUDGET_EXHAUSTED"
    assert outcome.minimality == "MINIMALITY_NOT_ESTABLISHED"


def test_multi_invariant_baseline_is_rejected() -> None:
    text = source() + "  - id: second\n    check: {$literal: true}\n"
    outcome = shrink_failed_scenario(request(text))
    assert outcome.status == "REJECTED"
    assert outcome.reason == "EXACTLY_ONE_POST_STATE_INVARIANT_REQUIRED"


def test_modified_invariant_or_target_rejected_by_scenario_identity() -> None:
    original = source()
    result, schedule, seed = failed_evidence(original)
    for changed in (
        original.replace("{$literal: 0}", "{$literal: -1}"),
        original.replace("{$literal: 1}", "{$literal: 2}"),
    ):
        outcome = shrink_failed_scenario(request(
            changed, result=result, schedule=schedule, schedule_seed=seed,
        ))
        assert outcome.status == "REJECTED"
        assert outcome.reason == "EVIDENCE_COORDINATES_OR_LINKAGE_MISMATCH"


def test_same_code_different_actor_and_same_actor_different_ordinal_rejected() -> None:
    item = request()
    assert item.result.failure is not None
    forged_actor = replace(item.result, failure=ResultFailure(
        "scenario:/actor/z-noise", "InvariantViolation", 0,
    ), result_hash="")
    forged_ordinal = replace(item.result, failure=ResultFailure(
        item.result.failure.actor, "InvariantViolation", 1,
    ), result_hash="")
    for result in (forged_actor, forged_ordinal):
        outcome = shrink_failed_scenario(replace(item, result=result))
        assert outcome.status == "REJECTED"
        assert outcome.reason == "EVIDENCE_COORDINATES_OR_LINKAGE_MISMATCH"


@pytest.mark.parametrize("changed", [
    ResultFailure("scenario:/actor/z-noise", "InvariantViolation", 0),
    ResultFailure("scenario:/actor/target", "InvariantViolation", 1),
])
def test_candidate_same_code_with_changed_failure_origin_or_ordinal_is_not_accepted(
    monkeypatch, changed,
) -> None:
    item = request()
    baseline_actor_count = len(validate_engine2(item.source).document.actors)
    run_failed = engine2_shrink._run_failed

    def changed_candidate_run(scenario, supplied, budget):
        run = run_failed(scenario, supplied, budget)
        if run is not None and len(scenario.document.actors) < baseline_actor_count:
            run = replace(run, result=replace(run.result, failure=changed, result_hash=""))
        return run

    monkeypatch.setattr(engine2_shrink, "_run_failed", changed_candidate_run)
    outcome = shrink_failed_scenario(item)
    assert outcome.status == "NO_REDUCTION"
    assert outcome.accepted_count == 0
    assert outcome.rejected_count == 1
    assert outcome.reduced_source == item.source


def test_wrong_seed_run_index_and_resource_coordinates_rejected() -> None:
    item = request()
    for changed in (
        replace(item, root_seed="other"), replace(item, schedule_seed=item.schedule_seed + 1),
        replace(item, run_index=3),
    ):
        assert shrink_failed_scenario(changed).reason == "EVIDENCE_COORDINATES_OR_LINKAGE_MISMATCH"
    text = source().replace("initial_state: {value: 0}\n", "initial_state: {value: 0}\nresources: {x: {$input: x}}\n")
    result, schedule, seed = failed_evidence_with_inputs(text, {"x": 1})
    changed = request(text, result=result, schedule=schedule, schedule_seed=seed, inputs={"x": 2})
    assert shrink_failed_scenario(changed).reason == "RESOURCE_COORDINATES_MISMATCH"


def failed_evidence_with_inputs(text, inputs):
    scenario = validate_engine2(text)
    from scenario_engine.engine2 import execute_engine2
    for seed in range(200):
        try:
            execute_engine2(scenario, "root", seed, run_index=2, inputs=inputs)
        except InvariantViolation as error:
            result = construct_result2(scenario, error.internal_outcome)
            if result.failure.selection_ordinal == 0:
                return result, error.internal_outcome.schedule, seed
    raise AssertionError("no fixture seed")


def test_invalid_dsl_duplicate_actor_and_invalid_transition_rejected() -> None:
    item = request()
    malformed = "dsl_version: 2\n"
    duplicate = item.source.replace("  - id: z-noise", "  - id: target")
    transition = item.source.replace("transition: null", "transition: missing", 1)
    for text in (malformed, duplicate, transition):
        outcome = shrink_failed_scenario(replace(item, source=text))
        assert outcome.status == "REJECTED" and outcome.reason == "BASELINE_MALFORMED_OR_INVALID"


def test_duplicate_yaml_key_alias_and_flow_actor_representation_rejected() -> None:
    item = request()
    duplicate = item.source.replace("scenario: shrink-case", "scenario: one\nscenario: two")
    alias = item.source.replace("initial_state: {value: 0}", "initial_state: &x {value: 0}").replace(
        "write: {value: {$state: value}}", "write: *x",
    )
    for text in (duplicate, alias):
        assert shrink_failed_scenario(replace(item, source=text)).reason == "BASELINE_MALFORMED_OR_INVALID"


def test_flow_style_actor_sequence_and_actor_mapping_are_rejected_before_execution() -> None:
    item = request()
    flow_sequence = """dsl_version: 2
scenario: shrink-case
clock: {start: '2026-01-01T00:00:00Z'}
initial_state: {value: 0}
actors: [{id: target, steps: [{id: fail, write: {value: {$literal: 1}}, transition: null}]}]
invariants:
  - id: stays-zero
    check: {$lte: [{$state: value}, {$literal: 0}]}
"""
    flow_mapping = flow_sequence.replace(
        "actors: [{id: target, steps: [{id: fail, write: {value: {$literal: 1}}, transition: null}]}]",
        "actors:\n  - {id: target, steps: [{id: fail, write: {value: {$literal: 1}}, transition: null}]}",
    )
    for text in (flow_sequence, flow_mapping):
        outcome = shrink_failed_scenario(replace(item, source=text))
        assert outcome.status == "REJECTED"
        assert outcome.reason == "BASELINE_MALFORMED_OR_INVALID"
        assert outcome.execution_count == 0


def test_valid_nonpreserving_candidate_is_rejected_and_budget_stop_is_honest(monkeypatch) -> None:
    item = request(source(("a-noise", "z-noise")), max_candidate_evaluations=1)

    def valid_but_changed(text, address):
        assert address == "scenario:/actor/a-noise"
        return source(("z-noise",), target_write=2)

    monkeypatch.setattr(engine2_shrink, "_delete_actor", valid_but_changed)
    outcome = shrink_failed_scenario(item)
    assert outcome.status == "NO_REDUCTION"
    assert outcome.reason == "EVALUATION_BUDGET_EXHAUSTED"
    assert outcome.candidate_evaluations == outcome.invalid_count == 1
    assert outcome.accepted_count == 0
    assert outcome.execution_count == 4
    assert outcome.minimality == "MINIMALITY_NOT_ESTABLISHED"
    assert not outcome.complete_final_pass


def test_malformed_result_schedule_and_null_error_evidence_rejected() -> None:
    item = request()
    assert shrink_failed_scenario(replace(item, result=b"{}")).reason == "BASELINE_MALFORMED_OR_INVALID"
    assert shrink_failed_scenario(replace(item, schedule=b"{}")).reason == "BASELINE_MALFORMED_OR_INVALID"
    with pytest.raises(Engine2ShrinkError):
        replace(item, result=None)


def test_unsupported_plugin_scenario_rejected_without_loading() -> None:
    text = source(plugin=True)
    # Evidence is deliberately borrowed: plugin exclusion occurs only after safe validation.
    item = request()
    outcome = shrink_failed_scenario(replace(item, source=text))
    assert outcome.reason == "PLUGINS_UNSUPPORTED"


def test_missing_required_input_is_rejected() -> None:
    text = source().replace("initial_state: {value: 0}\n", "initial_state: {value: 0}\nresources: {x: {$input: x}}\n")
    item = request()
    outcome = shrink_failed_scenario(replace(item, source=text))
    assert outcome.reason in {"EVIDENCE_COORDINATES_OR_LINKAGE_MISMATCH", "INPUTS_OR_RESOURCES_INVALID"}


def test_expected_suite_interpretation_cannot_replace_native_failed_evidence() -> None:
    item = request()
    successful = validate_engine2(source((), target_write=0))
    from scenario_engine.engine2 import execute_engine2
    result, schedule = execute_engine2(successful, "root", item.schedule_seed, run_index=2)
    outcome = shrink_failed_scenario(replace(item, result=result, schedule=schedule,
                                             source=source((), target_write=0)))
    assert outcome.reason == "NATIVE_FAILED_INVARIANT_VIOLATION_REQUIRED"


def test_original_schedule_is_incompatible_with_changed_scenario() -> None:
    item = request()
    outcome = shrink_failed_scenario(item)
    from scenario_engine.engine2 import replay_engine2
    with pytest.raises(Exception):
        replay_engine2(item.result, item.schedule, validate_engine2(outcome.reduced_source))


def test_inputs_are_defensively_copied_and_not_in_repr() -> None:
    supplied = {"secret": [1, 2]}
    item = request(inputs=supplied)
    supplied["secret"].append(3)
    assert tuple(item.inputs["secret"]) == (1, 2)
    assert "secret" not in repr(item)
    assert item.source not in repr(item)
    assert repr(item.result) not in repr(item)
    assert repr(item.schedule) not in repr(item)


def test_unusual_valid_actor_id_and_unicode_normalization_delete_whole_actor() -> None:
    decomposed = "caf\N{LATIN SMALL LETTER E}\N{COMBINING ACUTE ACCENT} / odd actor"
    text = source((decomposed,))
    item = request(text)
    outcome = shrink_failed_scenario(item)
    assert outcome.status == "REDUCED"
    assert outcome.removed_actor_addresses == ("scenario:/actor/caf%C3%A9%20%2F%20odd%20actor",)
    assert decomposed not in outcome.reduced_source
    assert outcome.reduced_counts["actors"] == 1


def test_cross_process_hashseed_stability() -> None:
    text = source(("z-noise", "a-noise"))
    code = f'''from time import monotonic
from scenario_engine.engine2 import validate_engine2,construct_result2,execute_engine2
from scenario_engine.engine2_shrink import *
from scenario_engine.invariants import InvariantViolation
s={text!r};c=validate_engine2(s)
for seed in range(200):
 try: execute_engine2(c,"root",seed,run_index=2)
 except InvariantViolation as e:
  r=construct_result2(c,e.internal_outcome)
  if r.failure.selection_ordinal==0: q=e.internal_outcome.schedule;break
x=shrink_failed_scenario(Engine2ShrinkRequest(s,r,q,"root",seed,2,None,64,300,monotonic()+300,3))
print(repr(({summary.__name__!r},x.status,x.reason,x.removed_actor_addresses,x.candidate_evaluations,x.execution_count,x.final_result_hash,x.final_schedule_hash,x.final_scenario_hash)))'''
    outputs = []
    for seed in ("1", "999"):
        env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONHASHSEED": seed,
               "PYTHONDONTWRITEBYTECODE": "1"}
        outputs.append(subprocess.check_output([sys.executable, "-c", code], cwd=ROOT, env=env))
    assert outputs[0] == outputs[1]


def test_no_package_root_export() -> None:
    import scenario_engine
    assert not hasattr(scenario_engine, "shrink_failed_scenario")


def test_repeated_canonical_native_output_is_identical() -> None:
    item = request(source(("z-noise", "a-noise")))
    one, two = shrink_failed_scenario(item), shrink_failed_scenario(item)
    assert canonical_result2_bytes(one.final_result) == canonical_result2_bytes(two.final_result)
    assert canonical_schedule_bytes(one.final_schedule) == canonical_schedule_bytes(two.final_schedule)


def test_evidence_input_size_bound_preserved() -> None:
    with pytest.raises(Engine2ShrinkError, match="bounded canonical input size"):
        request(inputs={"x": "x" * 262_144})


def test_documented_installed_consumer_example_is_executable() -> None:
    text = (ROOT / "docs/engine2-shrink.md").read_text(encoding="utf-8")
    marked = text.split("<!-- installed-consumer-example:start -->", 1)[1].split(
        "<!-- installed-consumer-example:end -->", 1,
    )[0]
    example = marked.split("```python\n", 1)[1].rsplit("```", 1)[0]
    exec(compile(example, "docs/engine2-shrink.md", "exec"), {})
