from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from scenario_engine.engine2 import (
    canonical_manifest2_bytes, canonical_result2_bytes, execute_engine2,
    replay_engine2, validate_engine2,
)
from scenario_engine.engine2_suite import (
    MAX_CASE_INPUT_BYTES, MAX_SUITE_CASES, MAX_TOTAL_INPUT_BYTES,
    Engine2CaseOutcome, Engine2CaseRequest, Engine2SuiteOutcome,
    Engine2SuiteBoundError, Engine2SuiteError, Engine2SuitePlan,
    Engine2SuiteVerificationError, canonical_engine2_suite_bytes,
    canonical_engine2_suite_identity_bytes, execute_engine2_suite,
    read_engine2_suite, verify_engine2_suite,
)
from scenario_engine.plugins import GeneratorPlugin, PluginRegistry
from scenario_engine.schedule import canonical_schedule_bytes


ROOT = Path(__file__).parents[1]


def source(*, failing: bool = False, plugin: bool = False) -> str:
    generate = (
        "        generate:\n"
        "          made: {$plugin: {name: test.counter, version: '1', args: {}}}\n"
        if plugin else ""
    )
    invariant = (
        "invariants:\n"
        "  - id: bounded\n"
        "    check: {$lte: [{$state: value}, {$literal: 0}]}\n"
        if failing else ""
    )
    return (
        "dsl_version: 2\nscenario: engine2-suite-case\n"
        "clock: {start: '2026-01-01T00:00:00Z'}\n"
        "initial_state: {value: 0}\nactors:\n"
        "  - id: actor\n    steps:\n      - id: write\n"
        + generate
        + "        write: {value: {$add: [{$state: value}, {$literal: 1}]}}\n"
        "        transition: null\n"
        + invariant
    )


def request(case_id: str = "case-1", **changes) -> Engine2CaseRequest:
    values = {"scenario": validate_engine2(source()), "root_seed": "root", "schedule_seed": 7}
    values.update(changes)
    return Engine2CaseRequest(case_id, **values)


def children(outcome):
    return {
        item.request["case_id"]: {
            "manifest": canonical_manifest2_bytes(item.result.manifest),
            "result": canonical_result2_bytes(item.result),
            "schedule": canonical_schedule_bytes(item.schedule),
        }
        for item in outcome.cases if item.result is not None
    }


def reaggregate(payload: dict) -> bytes:
    identity = {key: payload[key] for key in ("cases", "contract", "counts", "plan", "status")}
    payload["aggregate_hash"] = hashlib.sha256(json.dumps(
        identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def reidentify(payload: dict) -> bytes:
    """Recompute every affected identity after adversarial request mutation."""
    identities = []
    for case in payload["cases"]:
        case["case_identity"] = hashlib.sha256(json.dumps(
            case["request"], ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode()).hexdigest()
        identities.append(case["case_identity"])
    payload["plan"]["case_identities"] = identities
    plan_identity = {key: payload["plan"][key] for key in ("case_identities", "contract", "limits")}
    payload["plan"]["plan_hash"] = hashlib.sha256(json.dumps(
        plan_identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()
    return reaggregate(payload)


def test_success_order_independent_coordinates_and_native_bytes() -> None:
    scenario = validate_engine2(source())
    plan = Engine2SuitePlan((
        Engine2CaseRequest("first", scenario, "root-a", 3, run_index=4),
        Engine2CaseRequest("second", scenario, "root-b", 9, run_index=8),
    ))
    suite = execute_engine2_suite(plan)
    assert [item.request["case_id"] for item in suite.cases] == ["first", "second"]
    assert [item.request["position"] for item in suite.cases] == [0, 1]
    assert [item.request["root_seed"] for item in suite.cases] == ["root-a", "root-b"]
    assert [item.request["schedule_seed"] for item in suite.cases] == [3, 9]
    assert [item.request["run_index"] for item in suite.cases] == [4, 8]
    for case, coordinates in zip(suite.cases, (("root-a", 3, 4), ("root-b", 9, 8))):
        standalone = execute_engine2(scenario, coordinates[0], coordinates[1], run_index=coordinates[2])
        assert canonical_result2_bytes(case.result) == canonical_result2_bytes(standalone[0])
        assert canonical_schedule_bytes(case.schedule) == canonical_schedule_bytes(standalone[1])


def test_repeat_determinism_reordering_identity_and_state_isolation() -> None:
    one = request("one", root_seed="same", schedule_seed=1)
    two = request("two", root_seed="same", schedule_seed=2)
    first = execute_engine2_suite(Engine2SuitePlan((one, two)))
    again = execute_engine2_suite(Engine2SuitePlan((one, two)))
    reversed_suite = execute_engine2_suite(Engine2SuitePlan((two, one)))
    assert canonical_engine2_suite_bytes(first) == canonical_engine2_suite_bytes(again)
    assert first.aggregate_hash != reversed_suite.aggregate_hash
    assert first.plan["plan_hash"] != reversed_suite.plan["plan_hash"]
    assert [case.result.final_state["value"] for case in first.cases] == [1, 1]


def test_expected_invariant_failure_remains_native_failed_and_replays() -> None:
    scenario = validate_engine2(source(failing=True))
    suite = execute_engine2_suite(Engine2SuitePlan((Engine2CaseRequest(
        "expected", scenario, "root", 7,
        expected_classification="FAILED", expected_failure_code="InvariantViolation",
    ),)))
    case = suite.cases[0]
    assert suite.status == "SUCCESS" and case.status == "EXPECTED_FAILURE"
    assert case.result.classification == "FAILED"
    assert case.result.failure.code == case.schedule.failure.code == "InvariantViolation"
    assert replay_engine2(case.result, case.schedule, scenario) == case.result


def test_incorrect_failure_code_and_unexpected_failure_are_truthful() -> None:
    scenario = validate_engine2(source(failing=True))
    wrong = execute_engine2_suite(Engine2SuitePlan((Engine2CaseRequest(
        "wrong", scenario, "root", 7,
        expected_classification="FAILED", expected_failure_code="OtherFailure",
    ),)))
    undeclared = execute_engine2_suite(Engine2SuitePlan((Engine2CaseRequest(
        "undeclared", scenario, "root", 7,
    ),)))
    assert wrong.status == undeclared.status == "FAILED"
    assert wrong.cases[0].status == undeclared.cases[0].status == "UNEXPECTED_FAILURE"
    assert wrong.cases[0].observed["failure_code"] == "InvariantViolation"


def test_completed_status_matrix_rejects_forged_semantics() -> None:
    successful = execute_engine2_suite(Engine2SuitePlan((request(),))).cases[0]
    with pytest.raises(Engine2SuiteError, match="observation and expectation"):
        Engine2CaseOutcome(
            successful.request, successful.case_identity, "UNEXPECTED_FAILURE",
            successful.observed, successful.native, None,
        )
    failed_request = request(
        expected_classification="FAILED", expected_failure_code="UnsupportedFailure",
    )
    with pytest.raises(Engine2SuiteError, match="observation and expectation"):
        Engine2CaseOutcome(
            failed_request.coordinates, failed_request.case_identity, "EXPECTED_FAILURE",
            {"classification": "FAILED", "failure_code": "UnsupportedFailure"},
            successful.native, None,
        )


def test_plugin_failure_is_error_not_expected_and_is_redacted() -> None:
    secret = "PLUGIN-SECRET-SENTINEL"
    scenario = validate_engine2(source(plugin=True))

    def fail(context, arguments):
        raise RuntimeError(secret)

    registry = PluginRegistry((GeneratorPlugin("test.counter", "1", fail),))
    suite = execute_engine2_suite(Engine2SuitePlan((Engine2CaseRequest(
        "plugin", scenario, "root", 7, plugins=registry,
        expected_classification="FAILED", expected_failure_code="PluginExecutionError",
    ),)))
    encoded = canonical_engine2_suite_bytes(suite)
    assert suite.status == "FAILED" and suite.cases[0].status == "ERROR"
    assert suite.cases[0].native is None
    assert suite.cases[0].error["code"] == "PLUGIN_EXECUTION_FAILED"
    assert secret.encode() not in encoded and b"RuntimeError" not in encoded


def test_strict_offline_verification_and_exact_replay() -> None:
    suite = execute_engine2_suite(Engine2SuitePlan((request(),)))
    encoded = canonical_engine2_suite_bytes(suite)
    read = read_engine2_suite(encoded)
    assert canonical_engine2_suite_bytes(read) == encoded
    assert verify_engine2_suite(read, children(suite)).aggregate_hash == suite.aggregate_hash
    case = suite.cases[0]
    assert replay_engine2(case.result, case.schedule, request().scenario) == case.result


def test_duplicate_ids_bad_integer_types_cross_major_and_unsupported_plugins() -> None:
    with pytest.raises(Engine2SuiteError, match="duplicate case_id"):
        Engine2SuitePlan((request("same"), request("same", schedule_seed=8)))
    for values in ({"root_seed": True}, {"schedule_seed": True}, {"run_index": True}):
        with pytest.raises(Engine2SuiteError):
            request(**values)
    dsl1 = validate_engine2(source())
    with pytest.raises(Engine2SuiteError):
        Engine2CaseRequest("bad", object(), "root", 1)  # type: ignore[arg-type]
    assert dsl1.document.dsl_version == 2
    plugin_scenario = validate_engine2(source(plugin=True))
    with pytest.raises(Engine2SuiteError):
        Engine2CaseRequest("missing-plugin", plugin_scenario, "root", 1)
    with pytest.raises(Engine2SuiteError):
        Engine2CaseRequest("wrong-plugin", plugin_scenario, "root", 1, plugins=PluginRegistry((
            GeneratorPlugin("test.counter", "2", lambda c, a: 1),
        )))


def test_malformed_duplicate_unknown_versions_and_counters_fail() -> None:
    encoded = canonical_engine2_suite_bytes(execute_engine2_suite(Engine2SuitePlan((request(),))))
    with pytest.raises(Engine2SuiteError):
        read_engine2_suite(b"{")
    with pytest.raises(Engine2SuiteError, match="duplicate"):
        read_engine2_suite(encoded.replace(b'{"aggregate_hash":', b'{"aggregate_hash":"0","aggregate_hash":', 1))
    payload = json.loads(encoded); payload["unknown"] = 1
    with pytest.raises(Engine2SuiteError):
        read_engine2_suite(json.dumps(payload).encode())
    payload = json.loads(encoded); payload["cases"][0]["request"]["engine_version"] = "1.0.0"
    with pytest.raises(Engine2SuiteError):
        read_engine2_suite(reaggregate(payload))
    payload = json.loads(encoded); payload["counts"]["success"] = 0
    with pytest.raises(Engine2SuiteError):
        read_engine2_suite(reaggregate(payload))


def test_reference_clock_requires_canonical_aware_datetime_at_both_boundaries() -> None:
    suite = execute_engine2_suite(Engine2SuitePlan((request(),)))
    case = suite.cases[0]
    assert case.request["reference_clock_start"].isoformat() == "2026-01-01T00:00:00+00:00"
    for invalid in (1, True, "2026-01-01T00:00:00Z", None, datetime(2026, 1, 1)):
        forged = {**case.request, "reference_clock_start": invalid}
        with pytest.raises(Engine2SuiteError, match="timezone-aware datetime"):
            Engine2CaseOutcome(forged, case.case_identity, case.status, case.observed, case.native, None)

    encoded = canonical_engine2_suite_bytes(suite)
    malformed = (
        1,
        True,
        "2026-01-01T00:00:00Z",
        None,
        {"$type": "datetime", "value": "2026-01-01T00:00:00.000000"},
        {"$type": "datetime", "value": 1},
        {"$type": "datetime", "value": "2026-01-01T01:00:00.000000+01:00"},
    )
    for invalid in malformed:
        payload = json.loads(encoded)
        payload["cases"][0]["request"]["reference_clock_start"] = invalid
        with pytest.raises(Engine2SuiteError):
            read_engine2_suite(reidentify(payload))


def test_error_only_aggregate_still_rejects_forged_reference_clock() -> None:
    scenario = validate_engine2(source(plugin=True))
    registry = PluginRegistry((GeneratorPlugin(
        "test.counter", "1", lambda context, arguments: (_ for _ in ()).throw(RuntimeError("private")),
    ),))
    suite = execute_engine2_suite(Engine2SuitePlan((Engine2CaseRequest(
        "error-only", scenario, "root", 7, plugins=registry,
    ),)))
    assert suite.cases[0].status == "ERROR" and suite.cases[0].native is None
    payload = json.loads(canonical_engine2_suite_bytes(suite))
    payload["cases"][0]["request"]["reference_clock_start"] = None
    with pytest.raises(Engine2SuiteError, match="timezone-aware datetime"):
        read_engine2_suite(reidentify(payload))


def test_invalid_limits_resource_hashes_and_deep_values_fail_closed() -> None:
    encoded = canonical_engine2_suite_bytes(execute_engine2_suite(Engine2SuitePlan((request(),))))
    payload = json.loads(encoded)
    payload["plan"]["limits"] = []
    with pytest.raises(Engine2SuiteError):
        read_engine2_suite(json.dumps(payload).encode())
    payload = json.loads(encoded)
    payload["cases"][0]["request"]["input_resource_hashes"] = {"resource": "not-a-hash"}
    with pytest.raises(Engine2SuiteError):
        read_engine2_suite(json.dumps(payload).encode())
    nested = None
    for _ in range(40):
        nested = {"x": nested}
    with pytest.raises(Engine2SuiteBoundError, match="nesting depth"):
        request(inputs={"nested": nested})
    deep_json = b'{"x":' * 40 + b"null" + b"}" * 40
    with pytest.raises(Engine2SuiteBoundError, match="nesting depth"):
        read_engine2_suite(deep_json)


def test_error_record_table_and_error_native_exclusivity() -> None:
    item = request()
    observed = {"classification": None, "failure_code": None}
    valid = {
        "stage": "execution", "family": "INTERNAL",
        "code": "INTERNAL_EXECUTION_FAILED", "message": "case execution failed",
    }
    Engine2CaseOutcome(item.coordinates, item.case_identity, "ERROR", observed, None, valid)
    for change in (
        {"stage": "retention"}, {"family": "PLUGIN"},
        {"code": "PLUGIN_EXECUTION_FAILED"}, {"message": "exception detail"},
        {"unknown": "field"},
    ):
        forged = {**valid, **change}
        with pytest.raises(Engine2SuiteError):
            Engine2CaseOutcome(item.coordinates, item.case_identity, "ERROR", observed, None, forged)
    for field_name in ("stage", "family", "code"):
        for invalid in ([], {}, None, 1, True):
            with pytest.raises(Engine2SuiteError):
                Engine2CaseOutcome(
                    item.coordinates, item.case_identity, "ERROR", observed, None,
                    {**valid, field_name: invalid},
                )
    for invalid in ([], {}, None, 1, True):
        with pytest.raises(Engine2SuiteError):
            Engine2CaseOutcome(
                item.coordinates, item.case_identity, "ERROR", observed, None,
                {**valid, "message": invalid},
            )
    completed = execute_engine2_suite(Engine2SuitePlan((item,))).cases[0]
    with pytest.raises(Engine2SuiteError, match="only a redacted error"):
        Engine2CaseOutcome(
            item.coordinates, item.case_identity, "ERROR", observed, completed.native, valid,
        )


def test_reader_returns_stable_errors_for_unhashable_status_and_error_fields() -> None:
    successful = canonical_engine2_suite_bytes(execute_engine2_suite(Engine2SuitePlan((request(),))))
    for invalid in ([], {}, None, 1, True):
        payload = json.loads(successful)
        payload["cases"][0]["status"] = invalid
        with pytest.raises(Engine2SuiteError, match="status"):
            read_engine2_suite(reaggregate(payload))

    item = request()
    error_case = Engine2CaseOutcome(
        item.coordinates, item.case_identity, "ERROR",
        {"classification": None, "failure_code": None}, None,
        {"stage": "execution", "family": "INTERNAL", "code": "INTERNAL_EXECUTION_FAILED",
         "message": "case execution failed"},
    )
    error_suite = Engine2SuiteOutcome(
        Engine2SuitePlan((item,)).payload, (error_case,),
        {"error": 1, "expected_failure": 0, "success": 0, "total": 1, "unexpected_failure": 0},
        "FAILED",
    )
    encoded = canonical_engine2_suite_bytes(error_suite)
    for field_name in ("stage", "family", "code"):
        for invalid in ([], {}, None, 1, True):
            payload = json.loads(encoded)
            payload["cases"][0]["error"][field_name] = invalid
            with pytest.raises(Engine2SuiteError, match="error"):
                read_engine2_suite(reaggregate(payload))


def test_tampered_missing_and_swapped_native_children_fail() -> None:
    suite = execute_engine2_suite(Engine2SuitePlan((request("one", schedule_seed=1), request("two", schedule_seed=2))))
    evidence = children(suite)
    tampered = {case: dict(items) for case, items in evidence.items()}
    tampered["one"]["result"] += b" "
    with pytest.raises(Engine2SuiteVerificationError):
        verify_engine2_suite(suite, tampered)
    with pytest.raises(Engine2SuiteVerificationError):
        verify_engine2_suite(suite, {"one": evidence["one"]})
    swapped = {case: dict(items) for case, items in evidence.items()}
    swapped["one"]["schedule"], swapped["two"]["schedule"] = swapped["two"]["schedule"], swapped["one"]["schedule"]
    with pytest.raises(Engine2SuiteVerificationError):
        verify_engine2_suite(suite, swapped)
    swapped = {case: dict(items) for case, items in evidence.items()}
    swapped["one"]["result"], swapped["two"]["result"] = swapped["two"]["result"], swapped["one"]["result"]
    with pytest.raises(Engine2SuiteVerificationError):
        verify_engine2_suite(suite, swapped)


def test_bounds_plus_one_and_partial_retention_error(monkeypatch) -> None:
    with pytest.raises(Engine2SuiteBoundError):
        request(inputs={"x": "x" * MAX_CASE_INPUT_BYTES})
    with pytest.raises(Engine2SuiteBoundError):
        Engine2SuitePlan(tuple(request(f"c-{index}", schedule_seed=index) for index in range(MAX_SUITE_CASES + 1)))
    import scenario_engine.engine2_suite as module
    plan = Engine2SuitePlan((request("one"), request("two", schedule_seed=8)))
    original_native = module._native
    monkeypatch.setattr(module, "_native", lambda result, schedule: (
        original_native(result, schedule)[0], module.MAX_RETAINED_CHILD_BYTES + 1,
    ))
    suite = execute_engine2_suite(plan)
    assert [item.status for item in suite.cases] == ["ERROR", "ERROR"]
    assert all(item.native is None for item in suite.cases)
    assert suite.counts["error"] == 2 and suite.status == "FAILED"


def test_aggregate_input_bytes_positive_boundary_plus_one_and_forged_reader() -> None:
    assert Engine2SuitePlan((request(),))

    def sized_inputs(size: int) -> dict[str, str]:
        return {"x": "x" * (size - len(b'{"x":""}'))}

    boundary = tuple(Engine2CaseRequest(
        f"boundary-{index}", validate_engine2(source()), "root", index,
        inputs=sized_inputs(MAX_CASE_INPUT_BYTES),
    ) for index in range(MAX_TOTAL_INPUT_BYTES // MAX_CASE_INPUT_BYTES))
    assert sum(item.coordinates["input_bytes"] for item in Engine2SuitePlan(boundary).cases) == MAX_TOTAL_INPUT_BYTES

    plus_one = (
        Engine2CaseRequest("over-0", validate_engine2(source()), "root", 0,
                           inputs=sized_inputs(MAX_CASE_INPUT_BYTES - 1)),
        *(Engine2CaseRequest(f"over-{index}", validate_engine2(source()), "root", index,
                             inputs=sized_inputs(MAX_CASE_INPUT_BYTES)) for index in range(1, 16)),
        request("over-16", schedule_seed=16),
    )
    with pytest.raises(Engine2SuiteBoundError, match="MAX_TOTAL_INPUT_BYTES"):
        Engine2SuitePlan(plus_one)

    base = execute_engine2_suite(Engine2SuitePlan(tuple(
        request(f"forged-{index}", schedule_seed=index) for index in range(17)
    )))
    payload = json.loads(canonical_engine2_suite_bytes(base))
    for case in payload["cases"]:
        case["request"]["input_bytes"] = MAX_CASE_INPUT_BYTES
    forged = reidentify(payload)
    with pytest.raises(Engine2SuiteBoundError, match="MAX_TOTAL_INPUT_BYTES"):
        read_engine2_suite(forged)
    with pytest.raises(Engine2SuiteBoundError, match="MAX_TOTAL_INPUT_BYTES"):
        verify_engine2_suite(forged)


def test_selection_overrun_is_bounded_truthful_error(monkeypatch) -> None:
    import scenario_engine.engine2_suite as module
    monkeypatch.setattr(module, "MAX_CASE_SELECTIONS", 0)
    suite = execute_engine2_suite(Engine2SuitePlan((request(),)))
    case = suite.cases[0]
    assert case.status == "ERROR" and case.native is None
    assert case.error == {
        "code": "SELECTION_BOUND_EXCEEDED", "family": "LIMIT",
        "message": "aggregate scheduler selection bound exceeded", "stage": "retention",
    }


def test_recoverable_native_construction_error_is_retained_and_later_case_runs(monkeypatch) -> None:
    import scenario_engine.engine2 as engine2
    original = engine2.construct_result2
    calls = 0

    def fail_once(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("PRIVATE-OPERATIONAL-DETAIL")
        return original(*args, **kwargs)

    monkeypatch.setattr(engine2, "construct_result2", fail_once)
    suite = execute_engine2_suite(Engine2SuitePlan((request("one"), request("two", schedule_seed=8))))
    assert [case.status for case in suite.cases] == ["ERROR", "SUCCESS"]
    assert suite.cases[0].error["code"] == "INTERNAL_EXECUTION_FAILED"
    assert b"PRIVATE-OPERATIONAL-DETAIL" not in canonical_engine2_suite_bytes(suite)


def test_failed_result_construction_and_native_serialization_abort(monkeypatch) -> None:
    import scenario_engine.engine2_suite as module
    failing_request = Engine2CaseRequest(
        "failed", validate_engine2(source(failing=True)), "root", 7,
        expected_classification="FAILED", expected_failure_code="InvariantViolation",
    )
    monkeypatch.setattr(module, "construct_result2", lambda *args: (_ for _ in ()).throw(RuntimeError("broken result")))
    with pytest.raises(RuntimeError, match="broken result"):
        execute_engine2_suite(Engine2SuitePlan((failing_request,)))

    monkeypatch.undo()
    for serializer in ("canonical_result2_bytes", "canonical_schedule_bytes"):
        monkeypatch.setattr(module, serializer, lambda *args: (_ for _ in ()).throw(RuntimeError("broken serialization")))
        with pytest.raises(RuntimeError, match="broken serialization"):
            execute_engine2_suite(Engine2SuitePlan((request(),)))
        monkeypatch.undo()


def test_nonempty_input_resource_coordinates_link_without_replay_claim() -> None:
    scenario = validate_engine2(source().replace(
        "initial_state: {value: 0}\n",
        "initial_state: {value: 0}\nresources:\n  supplied: {$input: supplied}\n",
    ))
    item = Engine2CaseRequest("input", scenario, "root", 7, inputs={"supplied": {"private": 3}})
    suite = execute_engine2_suite(Engine2SuitePlan((item,)))
    case = suite.cases[0]
    assert case.request["input_hash"] == hashlib.sha256(item.input_canonical_bytes).hexdigest()
    assert case.request["input_resource_hashes"]
    assert verify_engine2_suite(read_engine2_suite(canonical_engine2_suite_bytes(suite)), children(suite))


def test_malformed_child_evidence_is_rejected_before_native_acceptance() -> None:
    suite = execute_engine2_suite(Engine2SuitePlan((request(),)))
    evidence = children(suite)
    malformed = {"case-1": {**evidence["case-1"], "extra": b"fabricated"}}
    with pytest.raises(Engine2SuiteVerificationError):
        verify_engine2_suite(suite, malformed)
    wrong_type = {"case-1": {**evidence["case-1"], "result": bytearray(evidence["case-1"]["result"])}}
    with pytest.raises(Engine2SuiteVerificationError):
        verify_engine2_suite(suite, wrong_type)  # type: ignore[arg-type]


def test_immutable_models_and_candidate_literal_vectors() -> None:
    plan = Engine2SuitePlan((request(),))
    suite = execute_engine2_suite(plan)
    with pytest.raises(FrozenInstanceError):
        suite.status = "FAILED"  # type: ignore[misc]
    with pytest.raises(TypeError):
        suite.counts["success"] = 0  # type: ignore[index]
    # Candidate literals are reviewed vectors, not frozen compatibility fixtures.
    assert plan.plan_hash == "b5a7167c25ac80aa327169f257676ab308d06ad55657edb6cadd18bbb01df24c"
    assert suite.aggregate_hash == "d0628db52047741b8ef972ecb503d3b770f17a852da9fdc83d9b19f3e565720f"
    assert hashlib.sha256(canonical_engine2_suite_identity_bytes(suite)).hexdigest() == suite.aggregate_hash


def test_cross_process_hash_seed_determinism() -> None:
    code = f'''from scenario_engine.engine2 import validate_engine2
from scenario_engine.engine2_suite import *
s=validate_engine2({source()!r});p=Engine2SuitePlan((Engine2CaseRequest("case-1",s,"root",7),))
print(canonical_engine2_suite_bytes(execute_engine2_suite(p)).hex())'''
    outputs = []
    for seed in ("1", "999"):
        environment = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONHASHSEED": seed,
                       "PYTHONDONTWRITEBYTECODE": "1"}
        outputs.append(subprocess.check_output([sys.executable, "-c", code], cwd=ROOT, env=environment))
    assert outputs[0] == outputs[1]
