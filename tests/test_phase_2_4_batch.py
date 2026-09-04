from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
from pathlib import Path
from threading import Event, Lock

import pytest

import scenario_engine
from scenario_engine.batch import (
    DEFAULT_RETAINED_RESULT_BYTES,
    MAX_BATCH_ITEMS,
    MAX_IN_FLIGHT,
    MAX_WORKERS,
    BatchPlan,
    BatchResultBoundError,
    BatchSizeBoundError,
    BatchStatus,
    DuplicateRunIdentityError,
    ExecutionMode,
    InvalidExecutionOptionError,
    InvalidStreamingBoundError,
    InvalidWorkerCountError,
    RunRequest,
    UnsupportedBatchItemError,
    execute_batch,
    stream_batch,
)
from scenario_engine.canonical import canonical_scenario_hash
from scenario_engine.composition import execute_composed_suite, load_composed_suite
from scenario_engine.dsl import compile_document, parse_yaml, run_scenario
from scenario_engine.errors import ScenarioEngineError
from scenario_engine.matrix import MatrixDimension, MatrixPlan, execute_matrix_case, expand_matrix
from scenario_engine.suite import BatchResultEnvelope, canonical_suite_bytes


def _scenario():
    return compile_document(parse_yaml("""dsl_version: 1
scenario: batch_case
clock: {start: '2026-01-01T00:00:00Z'}
resources:
  selected: {input: selected, required: true}
initial_state: {value: 0, random: 0}
steps:
  - id: apply
    generate:
      draw: {$int: [1, 100000]}
    write:
      value: {$resource: selected}
      random: {$local: draw}
    transition: null
"""))


def _request(run_id: str, *, selected: int = 1, run_index: int = 0, seed="seed"):
    return RunRequest(run_id, _scenario(), seed, run_index, "C", {"selected": selected})


def test_plan_is_immutable_and_defensively_isolates_caller_collections() -> None:
    nested = {"selected": [1, {"deep": [2]}]}
    source = [RunRequest("one", _scenario(), "seed", inputs=nested)]
    plan = BatchPlan(source)
    nested["selected"].append(3)
    nested["selected"][1]["deep"].append(4)
    source.clear()
    assert plan.items[0].inputs["selected"] == (1, {"deep": (2,)})
    assert plan.items[0].plan_position == 0
    with pytest.raises(FrozenInstanceError):
        plan.fail_fast = True


def test_order_identity_empty_and_duplicate_policies() -> None:
    first = _request("first", selected=1)
    second = _request("second", selected=2)
    plan = BatchPlan((first, second))
    same = BatchPlan((first, second))
    changed = BatchPlan((first, _request("second", selected=3)))
    reordered = BatchPlan((second, first))
    assert plan.plan_identity == same.plan_identity
    assert plan.plan_identity != changed.plan_identity
    assert plan.plan_identity != reordered.plan_identity
    assert [item.record.run_identity for item in execute_batch(plan).items] == ["first", "second"]
    empty = execute_batch(BatchPlan(()))
    assert empty.items == ()
    assert empty.envelope.manifest.success_count == 0
    assert empty.envelope.manifest.failure_count == 0
    assert empty.envelope.manifest.not_run_count == 0
    # Equal child work is not deduplicated; the unique run ID is the batch coordinate.
    duplicate_child = execute_batch(BatchPlan((_request("a"), _request("b"))))
    assert len(duplicate_child.items) == 2
    assert duplicate_child.items[0].record.child_identity == duplicate_child.items[1].record.child_identity
    with pytest.raises(DuplicateRunIdentityError):
        BatchPlan((_request("same"), _request("same")))
    consumed = False
    def generated():
        nonlocal consumed
        consumed = True
        yield _request("generated")
    with pytest.raises(ValueError):
        BatchPlan(generated())
    assert not consumed


def test_exact_batch_bound_and_execution_options(monkeypatch) -> None:
    import scenario_engine.batch.models as models

    monkeypatch.setattr(models, "MAX_BATCH_ITEMS", 2)
    assert len(BatchPlan((_request("a"), _request("b"))).items) == 2
    with pytest.raises(BatchSizeBoundError):
        BatchPlan((_request("a"), _request("b"), _request("c")))
    assert MAX_BATCH_ITEMS == 10_000
    assert MAX_WORKERS == MAX_IN_FLIGHT == 64
    assert DEFAULT_RETAINED_RESULT_BYTES == 256 * 1024 * 1024
    with pytest.raises(InvalidWorkerCountError):
        execute_batch(BatchPlan(()), workers=0)
    with pytest.raises(InvalidWorkerCountError):
        execute_batch(BatchPlan(()), workers=65)
    with pytest.raises(InvalidStreamingBoundError):
        execute_batch(BatchPlan(()), workers=2, max_in_flight=1)
    with pytest.raises(InvalidExecutionOptionError):
        execute_batch(BatchPlan((), fail_fast=True), workers=2)


def test_independent_contexts_reverse_order_and_worker_count_are_byte_identical() -> None:
    plan = BatchPlan(tuple(_request(f"run-{index}", selected=index, run_index=index) for index in range(4)))
    serial = execute_batch(plan, workers=1)
    parallel = execute_batch(plan, workers=4, max_in_flight=4)
    assert canonical_suite_bytes(serial.envelope) == canonical_suite_bytes(parallel.envelope)
    assert [item.result.to_json_bytes() for item in serial.items] == [
        item.result.to_json_bytes() for item in parallel.items
    ]
    standalone = {
        request.run_id: run_scenario(
            request.target, request.root_seed, run_index=request.run_index,
            locale=request.locale, inputs={"selected": request.inputs["selected"]},
        ).to_json_bytes()
        for request in reversed(plan.items)
    }
    assert standalone == {item.request.run_id: item.result.to_json_bytes() for item in serial.items}


def test_controlled_completion_inversion_never_changes_canonical_order(monkeypatch) -> None:
    import scenario_engine.batch.runtime as runtime

    original = runtime._execute
    release_first = Event()
    second_started = Event()

    def inverted(request):
        if request.run_id == "first":
            assert second_started.wait(5)
            release_first.wait(5)
        else:
            second_started.set()
            result = original(request)
            release_first.set()
            return result
        return original(request)

    monkeypatch.setattr(runtime, "_execute", inverted)
    execution = execute_batch(
        BatchPlan((_request("first"), _request("second"))), workers=2, max_in_flight=2
    )
    assert [item.record.run_identity for item in execution.items] == ["first", "second"]
    assert [item.run_identity for item in execution.envelope.manifest.items] == ["first", "second"]


class ExpectedFailure(ScenarioEngineError):
    code = "test.expected_failure"


def test_stable_failure_mixed_summary_fail_fast_and_no_retry(monkeypatch) -> None:
    import scenario_engine.batch.runtime as runtime

    original = runtime.run_scenario
    calls: list[str] = []

    def fail_selected(target, root_seed, **kwargs):
        selected = kwargs["inputs"]["selected"]
        calls.append(str(selected))
        if selected == 2:
            raise ExpectedFailure("secret /Users/person traceback-like detail")
        return original(target, root_seed, **kwargs)

    monkeypatch.setattr(runtime, "run_scenario", fail_selected)
    plan = BatchPlan((_request("ok", selected=1), _request("bad", selected=2), _request("later", selected=3)))
    result = execute_batch(plan, workers=2)
    records = result.envelope.manifest.items
    assert [item.status for item in records] == [BatchStatus.SUCCESS, BatchStatus.FAILURE, BatchStatus.SUCCESS]
    assert (result.envelope.manifest.success_count, result.envelope.manifest.failure_count) == (2, 1)
    assert records[1].failure.family == "ExpectedFailure"
    assert records[1].failure.code == "test.expected_failure"
    assert records[1].failure.message == "ExpectedFailure occurred"
    assert "/Users/" not in canonical_suite_bytes(result.envelope).decode()
    assert calls.count("2") == 1

    calls.clear()
    fast = execute_batch(BatchPlan(plan.items, fail_fast=True), workers=1)
    assert [item.record.status for item in fast.items] == [
        BatchStatus.SUCCESS, BatchStatus.FAILURE, BatchStatus.NOT_RUN
    ]
    assert calls == ["1", "2"]


def test_result_byte_budget_is_enforced_before_complete_retention() -> None:
    with pytest.raises(BatchResultBoundError):
        execute_batch(BatchPlan((_request("large"),), retained_result_bytes=1))


def test_matrix_case_preserves_case_identity_original_index_and_standalone_result() -> None:
    target = _scenario()
    matrix = MatrixPlan(
        target.scenario_id, canonical_scenario_hash(target),
        (MatrixDimension("selected", (10, 20, 30)),),
        ({"$ne": [{"$parameter": "selected"}, {"$literal": 20}]},),
        "matrix-seed", "C", target,
    )
    case = expand_matrix(matrix)[1]
    request = RunRequest(
        "matrix-run", matrix, matrix.root_seed, case.case_index, matrix.locale,
        execution_mode=ExecutionMode.MATRIX_CASE, matrix_case=case,
    )
    item = execute_batch(BatchPlan((request,))).items[0]
    standalone = execute_matrix_case(matrix, case)
    assert case.case_index == 2
    assert item.request.matrix_case.case_id == case.case_id
    assert item.record.child_identity == "matrix-case:" + case.case_id
    assert item.result.to_json_bytes() == standalone.to_json_bytes()
    with pytest.raises(UnsupportedBatchItemError):
        RunRequest("bad", matrix, matrix.root_seed)


def test_composed_suite_identity_and_execution_are_preserved(tmp_path: Path) -> None:
    (tmp_path / "mods").mkdir()
    (tmp_path / "mods/value.yaml").write_text(
        "dsl_version: 1\nmodule: value\nresources:\n  selected: {input: selected, required: true}\n",
        encoding="utf-8",
    )
    (tmp_path / "root.yaml").write_text("""dsl_version: 1
scenario: composed_batch
clock: {start: '2026-01-01T00:00:00Z'}
composition:
  modules: {value: mods/value.yaml}
initial_state: {selected: 0}
steps:
  - id: apply
    write: {selected: {$resource: value.selected}}
    transition: null
""", encoding="utf-8")
    suite = load_composed_suite("root.yaml", composition_root=tmp_path)
    request = RunRequest(
        "composed", suite, "seed", inputs={"selected": 7},
        execution_mode=ExecutionMode.COMPOSED,
    )
    item = execute_batch(BatchPlan((request,))).items[0]
    standalone = execute_composed_suite(suite, "seed", inputs={"selected": 7}).result
    assert item.record.child_identity == "suite:" + suite.composed_hash
    assert item.result.to_json_bytes() == standalone.to_json_bytes()


def test_ordered_stream_matches_complete_semantics_and_consumer_pacing() -> None:
    plan = BatchPlan(tuple(_request(f"run-{index}", selected=index) for index in range(5)))
    complete = execute_batch(plan, workers=3, max_in_flight=3)
    stream = stream_batch(plan, workers=3, max_in_flight=3)
    streamed = []
    iterator = iter(stream)
    streamed.append(next(iterator))
    streamed.extend(iterator)
    assert [item.record for item in streamed] == [item.record for item in complete.items]
    assert canonical_suite_bytes(stream.envelope) == canonical_suite_bytes(complete.envelope)
    assert stream.max_in_flight == 3
    assert isinstance(stream.envelope, BatchResultEnvelope)


def test_public_boundary_version_preservation_and_static_safety() -> None:
    from scenario_engine._version import VERSION

    assert "BatchPlan" not in scenario_engine.__all__
    assert VERSION == "1.0.0"
    forbidden = {"random", "secrets", "socket", "subprocess", "importlib", "os", "time", "urllib"}
    root = Path(__file__).parents[1] / "src/scenario_engine/batch"
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
            assert not isinstance(node, (ast.Global, ast.Nonlocal))
        assert imported.isdisjoint(forbidden)
