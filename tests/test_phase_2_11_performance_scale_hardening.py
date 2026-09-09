"""Deterministic Phase 2 scale baselines and hard-bound regression guards.

Timing is deliberately confined to this test module.  The broad ceilings detect
catastrophic regressions without making semantic behavior depend on wall time.
"""

from __future__ import annotations

from pathlib import Path
from statistics import median
from time import perf_counter

import pytest

from scenario_engine.batch import (
    DEFAULT_RETAINED_RESULT_BYTES,
    MAX_BATCH_ITEMS,
    MAX_IN_FLIGHT,
    MAX_WORKERS,
    BatchPlan,
    BatchResultBoundError,
    BatchSizeBoundError,
    InvalidWorkerCountError,
    RunRequest,
    execute_batch,
    stream_batch,
)
from scenario_engine.canonical import canonical_scenario_hash
from scenario_engine.cli import main as cli_main
from scenario_engine.composition import (
    MAX_AGGREGATE_INPUT_BYTES,
    MAX_CANONICAL_COMPOSED_BYTES,
    MAX_MODULE_DOCUMENT_BYTES,
    MAX_MODULES,
    MAX_ROOT_DOCUMENT_BYTES,
    CompositionBoundError,
    canonical_composition_bytes,
    load_composed_suite,
)
from scenario_engine.diff import (
    DEFAULT_MAX_DIFF_RECORDS,
    HARD_MAX_DIFF_RECORDS,
    MAX_COMPARED_ITEMS,
    MAX_DIFF_BYTES,
    MAX_DIFF_DEPTH,
    DiffBoundError,
    DiffMode,
    compare_inspection_documents,
)
from scenario_engine.domain_packs import (
    MAX_ASSETS_PER_PACK,
    MAX_CANONICAL_PACK_BYTES,
    MAX_PACKS_PER_REGISTRY,
    DomainPack,
    DomainPackBoundError,
    DomainPackRegistry,
)
from scenario_engine.dsl import compile_document, parse_yaml
from scenario_engine.inspection import (
    MAX_EXPLANATION_RECORDS,
    MAX_INSPECTION_BYTES,
    MAX_INSPECTION_DEPTH,
    MAX_INSPECTION_RECORDS,
    MAX_INSPECTION_SECTIONS,
    EvidenceAvailability,
    EvidenceValue,
    InspectionBoundError,
    InspectionDocument,
    InspectionSection,
    canonical_inspection_bytes,
)
from scenario_engine.matrix import (
    MAX_DIMENSIONS,
    MAX_RAW_CARDINALITY,
    MAX_RETAINED_CASES,
    MAX_VALUES_PER_DIMENSION,
    MatrixCardinalityError,
    MatrixDimension,
    MatrixPlan,
    expand_matrix,
)
from scenario_engine.oracle_assertions import (
    MAX_ASSERTIONS,
    MAX_ASSERTION_BYTES,
    MAX_ASSERTION_PATH_DEPTH,
    MAX_ASSERTION_SCAN_RECORDS,
    OracleAssertion,
    OracleAssertionBoundError,
    OracleAssertionKind,
    evaluate_assertions,
)
from scenario_engine.suite import canonical_suite_bytes


GUARDRAILS = {
    "composition_32_modules": 10.0,
    "matrix_10000_cases": 5.0,
    "batch_250_runs_serial": 15.0,
    "inspection_10000_values": 5.0,
    "diff_10000_records": 8.0,
    "domain_pack_750_registry": 5.0,
    "oracle_1000_assertions": 5.0,
    "oracle_scan_50000_records": 5.0,
}


def _measure(name: str, operation, *, repeats: int = 3):
    samples = []
    result = None
    for _ in range(repeats):
        started = perf_counter()
        result = operation()
        samples.append(perf_counter() - started)
    measured = median(samples)
    print(
        f"PHASE2_11_METRIC name={name} seconds={measured:.6f} "
        f"minimum={min(samples):.6f} guardrail={GUARDRAILS[name]:.3f}"
    )
    assert measured < GUARDRAILS[name]
    return result


def _scenario():
    return compile_document(parse_yaml("""dsl_version: 1
scenario: scale_case
clock: {start: '2026-01-01T00:00:00Z'}
resources:
  selected: {input: selected, required: true}
initial_state: {selected: 0}
steps:
  - id: apply
    write: {selected: {$resource: selected}}
    transition: null
"""))


def _document(value) -> InspectionDocument:
    return InspectionDocument(
        "scale",
        (InspectionSection("value", EvidenceValue(EvidenceAvailability.AVAILABLE, value)),),
    )


def _write_composition(root: Path, count: int = 32) -> None:
    modules = []
    for index in range(count):
        alias = f"m{index:02d}"
        modules.append(f"    {alias}: modules/{alias}.yaml")
        path = root / "modules" / f"{alias}.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"dsl_version: 1\nmodule: {alias}\nresources:\n  value: {index}\n",
            encoding="utf-8",
        )
    (root / "root.yaml").write_text(
        "dsl_version: 1\nscenario: composition_scale\n"
        "clock: {start: '2026-01-01T00:00:00Z'}\n"
        "composition:\n  modules:\n" + "\n".join(modules) + "\n"
        "initial_state: {value: 0}\nsteps:\n"
        "  - id: apply\n    write: {value: {$resource: m31.value}}\n    transition: null\n",
        encoding="utf-8",
    )


def test_frozen_bound_inventory_is_exact() -> None:
    assert (MAX_MODULES, MAX_ROOT_DOCUMENT_BYTES, MAX_MODULE_DOCUMENT_BYTES) == (64, 1 << 20, 1 << 20)
    assert (MAX_AGGREGATE_INPUT_BYTES, MAX_CANONICAL_COMPOSED_BYTES) == (16 << 20, 16 << 20)
    assert (MAX_DIMENSIONS, MAX_VALUES_PER_DIMENSION) == (16, 1_000)
    assert (MAX_RAW_CARDINALITY, MAX_RETAINED_CASES) == (100_000, 10_000)
    assert (MAX_BATCH_ITEMS, MAX_WORKERS, MAX_IN_FLIGHT) == (10_000, 64, 64)
    assert DEFAULT_RETAINED_RESULT_BYTES == 256 << 20
    assert (MAX_INSPECTION_SECTIONS, MAX_INSPECTION_RECORDS) == (32, 100_000)
    assert (MAX_EXPLANATION_RECORDS, MAX_INSPECTION_DEPTH, MAX_INSPECTION_BYTES) == (100_000, 64, 256 << 20)
    assert (DEFAULT_MAX_DIFF_RECORDS, HARD_MAX_DIFF_RECORDS) == (10_000, 100_000)
    assert (MAX_DIFF_DEPTH, MAX_COMPARED_ITEMS, MAX_DIFF_BYTES) == (64, 1_000_000, 256 << 20)
    assert (MAX_PACKS_PER_REGISTRY, MAX_ASSETS_PER_PACK, MAX_CANONICAL_PACK_BYTES) == (1_000, 10_000, 16 << 20)
    assert (MAX_ASSERTIONS, MAX_ASSERTION_PATH_DEPTH) == (1_000, 64)
    assert (MAX_ASSERTION_SCAN_RECORDS, MAX_ASSERTION_BYTES) == (100_000, 1 << 20)


def test_composition_scale_hash_stability_and_early_module_rejection(tmp_path: Path, monkeypatch) -> None:
    _write_composition(tmp_path)
    suite = _measure("composition_32_modules", lambda: load_composed_suite("root.yaml", composition_root=tmp_path))
    assert [module.alias for module in suite.modules] == sorted(module.alias for module in suite.modules)
    assert canonical_composition_bytes(suite) == canonical_composition_bytes(
        load_composed_suite("root.yaml", composition_root=tmp_path)
    )

    import scenario_engine.composition.resolver as resolver
    monkeypatch.setattr(resolver, "MAX_MODULES", 1)
    original_read = resolver._read_bounded
    reads = 0
    def root_only(*args):
        nonlocal reads
        reads += 1
        if reads > 1:
            pytest.fail("module read after root bound")
        return original_read(*args)
    monkeypatch.setattr(resolver, "_read_bounded", root_only)
    with pytest.raises(CompositionBoundError, match="exceeds 1 modules"):
        load_composed_suite("root.yaml", composition_root=tmp_path)


def test_matrix_scale_indexes_and_bounds_reject_before_uncontrolled_product(monkeypatch) -> None:
    plan = MatrixPlan(
        "scale", "0" * 64,
        (MatrixDimension("a", tuple(range(100))), MatrixDimension("b", tuple(range(100)))),
        ({"$ne": [{"$parameter": "b"}, {"$literal": 1}]},), "seed",
    )
    cases = _measure("matrix_10000_cases", lambda: expand_matrix(plan))
    assert len(cases) == 9_900
    assert [case.case_index for case in cases[:3]] == [0, 2, 3]

    import scenario_engine.matrix.expand as implementation
    monkeypatch.setattr(implementation, "product", lambda *args: pytest.fail("product was materialized"))
    over = MatrixPlan(
        "scale", "0" * 64,
        (MatrixDimension("a", tuple(range(101))), MatrixDimension("b", tuple(range(1_000)))),
        root_seed="seed",
    )
    with pytest.raises(MatrixCardinalityError, match="pre-filter"):
        expand_matrix(over)

    monkeypatch.undo()
    retained = MatrixPlan(
        "scale", "0" * 64,
        (MatrixDimension("a", tuple(range(100))), MatrixDimension("b", tuple(range(101)))),
        root_seed="seed",
    )
    with pytest.raises(MatrixCardinalityError, match="retained"):
        expand_matrix(retained)


def test_batch_scale_worker_semantics_stream_bound_and_hard_rejections(monkeypatch) -> None:
    target = _scenario()
    requests = tuple(RunRequest(f"run-{index:04d}", target, "seed", index, inputs={"selected": index}) for index in range(250))
    plan = BatchPlan(requests)
    serial = _measure("batch_250_runs_serial", lambda: execute_batch(plan, workers=1))
    parallel = execute_batch(plan, workers=8, max_in_flight=16)
    assert canonical_suite_bytes(serial.envelope) == canonical_suite_bytes(parallel.envelope)
    assert [item.result.to_json_bytes() for item in serial.items] == [item.result.to_json_bytes() for item in parallel.items]
    stream = stream_batch(plan, workers=8, max_in_flight=16)
    assert stream.max_in_flight == 16
    assert [item.record for item in stream] == [item.record for item in serial.items]
    with pytest.raises(InvalidWorkerCountError):
        execute_batch(BatchPlan(()), workers=MAX_WORKERS + 1)
    with pytest.raises(BatchResultBoundError):
        execute_batch(BatchPlan(requests[:1], retained_result_bytes=1))

    import scenario_engine.batch.models as models
    monkeypatch.setattr(models, "MAX_BATCH_ITEMS", 2)
    with pytest.raises(BatchSizeBoundError):
        BatchPlan(requests[:3])


def test_inspection_large_document_and_depth_record_byte_bounds(monkeypatch) -> None:
    values = tuple({"index": index, "value": f"v{index}"} for index in range(10_000))
    document = _measure("inspection_10000_values", lambda: _document(values))
    encoded = canonical_inspection_bytes(document)
    assert b"seconds" not in encoded and b"guardrail" not in encoded

    import scenario_engine.inspection.models as models
    monkeypatch.setattr(models, "MAX_INSPECTION_RECORDS", 10)
    with pytest.raises(InspectionBoundError, match="traversal"):
        _document(tuple(range(11)))
    monkeypatch.setattr(models, "MAX_INSPECTION_DEPTH", 2)
    with pytest.raises(InspectionBoundError, match="nesting"):
        _document({"a": {"b": {"c": 1}}})
    import scenario_engine.inspection.serialization as serialization
    monkeypatch.setattr(serialization, "MAX_INSPECTION_BYTES", 1)
    with pytest.raises(InspectionBoundError, match="canonical inspection"):
        serialization.canonical_inspection_bytes(_document(1))


def test_diff_scale_first_complete_and_bounded_truncation(monkeypatch) -> None:
    left = _document({f"k{index:05d}": 0 for index in range(10_001)})
    right = _document({f"k{index:05d}": 1 for index in range(10_001)})
    complete = _measure(
        "diff_10000_records",
        lambda: compare_inspection_documents(left, right, max_records=DEFAULT_MAX_DIFF_RECORDS),
    )
    assert len(complete.records) == 10_000 and complete.truncated and complete.omitted_count == 1
    assert complete.records == compare_inspection_documents(left, right, max_records=10_000).records

    import scenario_engine.diff.compare as implementation
    original_emit = implementation._Traversal.emit
    calls = 0
    def counted(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        return original_emit(self, *args, **kwargs)
    monkeypatch.setattr(implementation._Traversal, "emit", counted)
    first = compare_inspection_documents(left, right, mode=DiffMode.FIRST)
    assert len(first.records) == calls == 1
    with pytest.raises(DiffBoundError):
        compare_inspection_documents(left, right, max_records=HARD_MAX_DIFF_RECORDS + 1)


def test_domain_pack_registry_scale_sorted_resolution_and_over_bound(monkeypatch) -> None:
    packs = tuple(DomainPack(f"example.p{index:04d}", "1") for index in reversed(range(750)))
    registry = _measure("domain_pack_750_registry", lambda: DomainPackRegistry(packs))
    assert tuple(pack.name for pack in registry) == tuple(sorted(pack.name for pack in packs))
    resolved = registry.resolve_all((("example.p0749", "1"), ("example.p0000", "1")))
    assert tuple(pack.name for pack in resolved) == ("example.p0000", "example.p0749")

    import scenario_engine.domain_packs.registry as implementation
    monkeypatch.setattr(implementation, "MAX_PACKS_PER_REGISTRY", 2)
    with pytest.raises(DomainPackBoundError, match="exceeds 2 packs"):
        implementation.DomainPackRegistry(packs[:3])


def test_oracle_many_assertions_scan_bound_and_deterministic_order(monkeypatch) -> None:
    doc = _document({"present": 1})
    assertions = tuple(
        OracleAssertion(f"a{index:04d}", OracleAssertionKind.PRESENT, "/value/present")
        for index in range(1_000)
    )
    evaluation = _measure("oracle_1000_assertions", lambda: evaluate_assertions(doc, assertions))
    assert [result.assertion_id for result in evaluation.results] == [item.assertion_id for item in assertions]

    records = tuple("hit" if index == 49_999 else "miss" for index in range(50_000))
    scan_doc = InspectionDocument(
        "scale", (InspectionSection("records", EvidenceValue(EvidenceAvailability.AVAILABLE, records)),)
    )
    scan = OracleAssertion(
        "scan", OracleAssertionKind.OCCURRENCE_COUNT, "/records", 1,
        {"predicate": {"path": "", "operator": "equal", "expected": "hit"}},
    )
    scan_result = _measure("oracle_scan_50000_records", lambda: evaluate_assertions(scan_doc, (scan,)))
    assert scan_result.results[0].outcome.value == "pass"

    import importlib
    implementation = importlib.import_module("scenario_engine.oracle_assertions.evaluate")
    monkeypatch.setattr(implementation, "MAX_ASSERTION_SCAN_RECORDS", 10)
    with pytest.raises(OracleAssertionBoundError, match="scan exceeds 10"):
        evaluate_assertions(scan_doc, (scan,))


def test_timing_metrics_never_enter_cli_or_semantic_output(tmp_path: Path, capsys) -> None:
    target = _scenario()
    result = execute_batch(BatchPlan((RunRequest("one", target, "seed", inputs={"selected": 1}),)))
    semantic = canonical_suite_bytes(result.envelope)
    assert all(token not in semantic for token in (b"seconds", b"guardrail", b"perf_counter"))

    scenario_path = tmp_path / "scenario.yaml"
    scenario_path.write_text("""dsl_version: 1
scenario: cli_scale
clock: {start: '2026-01-01T00:00:00Z'}
initial_state: {value: 0}
steps:
  - id: finish
    write: {value: {$literal: 0}}
    transition: null
""", encoding="utf-8")
    assert cli_main(["--json", "hash", str(scenario_path)]) == 0
    output = capsys.readouterr().out
    assert "seconds" not in output and "guardrail" not in output
