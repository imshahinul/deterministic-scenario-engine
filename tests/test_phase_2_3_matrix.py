from __future__ import annotations

import ast
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

import scenario_engine
from scenario_engine.canonical import canonical_scenario_hash
from scenario_engine._version import VERSION
from scenario_engine.composition import load_composed_suite
from scenario_engine.dsl import compile_document, parse_yaml
from scenario_engine.matrix import (
    MAX_RAW_CARDINALITY,
    DuplicateMatrixCaseError,
    MatrixCardinalityError,
    MatrixDimension,
    MatrixDimensionError,
    MatrixFilterError,
    MatrixPlan,
    execute_matrix,
    execute_matrix_case,
    expand_matrix,
    select_matrix_case,
)
from scenario_engine.suite import MatrixManifest, MatrixResultEnvelope, canonical_suite_bytes


def _plan(*dimensions, filters=(), suite_hash="0" * 64, target=None):
    return MatrixPlan("example", suite_hash, tuple(dimensions), tuple(filters), "seed", "C", target)


def _scenario():
    return compile_document(parse_yaml("""dsl_version: 1
scenario: matrix_case
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


def _scenario_plan(*, filters=()):
    target = _scenario()
    return MatrixPlan(
        target.scenario_id,
        canonical_scenario_hash(target),
        (MatrixDimension("selected", (10, 20, 30)),),
        filters,
        "root-seed",
        "C",
        target,
    )


def test_plan_defensively_isolates_caller_collections_and_typed_values() -> None:
    nested = {"amount": [Decimal("1.20"), datetime(2026, 1, 1, tzinfo=timezone.utc)]}
    values = [nested]
    dimensions = [MatrixDimension("region", values)]
    filters = [{"$literal": True}]
    plan = _plan(*dimensions, filters=filters)
    nested["amount"].append(99)
    values.append("later")
    dimensions.clear()
    filters[0]["$literal"] = False
    assert len(plan.dimensions) == 1
    assert plan.dimensions[0].values[0]["amount"] == (
        Decimal("1.20"), datetime(2026, 1, 1, tzinfo=timezone.utc)
    )
    assert dict(plan.filters[0]) == {"$literal": True}


def test_exact_two_and_three_dimension_odometer_order_and_repeatability() -> None:
    two = _plan(MatrixDimension("a", (1, 2)), MatrixDimension("b", ("x", "y")))
    assert [tuple(case.assignment.values()) for case in expand_matrix(two)] == [
        (1, "x"), (1, "y"), (2, "x"), (2, "y")
    ]
    three = _plan(
        MatrixDimension("a", (1, 2)), MatrixDimension("b", ("x", "y")),
        MatrixDimension("c", (False, True)),
    )
    expected = [
        (1, "x", False), (1, "x", True), (1, "y", False), (1, "y", True),
        (2, "x", False), (2, "x", True), (2, "y", False), (2, "y", True),
    ]
    first = expand_matrix(three)
    assert [tuple(case.assignment.values()) for case in first] == expected
    assert first == expand_matrix(three)


def test_original_indexes_are_assigned_before_pure_filtering() -> None:
    plan = _plan(
        MatrixDimension("n", tuple(range(6))),
        filters=({"$or": [
            {"$eq": [{"$parameter": "n"}, {"$literal": 0}]},
            {"$eq": [{"$parameter": "n"}, {"$literal": 2}]},
            {"$eq": [{"$parameter": "n"}, {"$literal": 5}]},
        ]},),
    )
    first = expand_matrix(plan)
    assert [case.case_index for case in first] == [0, 2, 5]
    assert first == expand_matrix(plan)


def test_filter_removing_neighbor_does_not_shift_retained_case_identity() -> None:
    dimension = MatrixDimension("n", (0, 1, 2))
    complete = _plan(dimension)
    filtered = _plan(
        dimension,
        filters=({"$ne": [{"$parameter": "n"}, {"$literal": 0}]},),
    )
    assert expand_matrix(complete)[2] == expand_matrix(filtered)[1]
    with pytest.raises(MatrixFilterError):
        expand_matrix(_plan(dimension, filters=({"$parameter": "n"},)))


def test_assignment_and_original_position_participate_in_case_identity() -> None:
    first = expand_matrix(_plan(MatrixDimension("n", (1, 2))))
    changed = expand_matrix(_plan(MatrixDimension("n", (1, 3))))
    assert first[0].case_id == changed[0].case_id
    assert first[1].case_id != changed[1].case_id
    assert first[0].case_id != first[1].case_id


def test_duplicate_canonical_assignment_is_rejected_not_coalesced() -> None:
    with pytest.raises(DuplicateMatrixCaseError):
        expand_matrix(_plan(MatrixDimension("n", (1, 1))))


def test_empty_and_invalid_dimension_semantics() -> None:
    empty_assignment = expand_matrix(_plan())
    assert len(empty_assignment) == 1
    assert empty_assignment[0].case_index == 0
    assert dict(empty_assignment[0].assignment) == {}
    with pytest.raises(MatrixDimensionError):
        MatrixDimension("empty", ())
    filtered = _plan(filters=({"$literal": False},))
    assert expand_matrix(filtered) == ()


def test_cardinality_exact_limit_passes_and_over_limit_fails_before_product(monkeypatch) -> None:
    exact = _plan(
        MatrixDimension("a", tuple(range(100))),
        MatrixDimension("b", tuple(range(1000))),
        filters=({"$literal": False},),
    )
    assert expand_matrix(exact) == ()
    over = _plan(
        MatrixDimension("a", tuple(range(101))),
        MatrixDimension("b", tuple(range(1000))),
    )
    called = False
    import scenario_engine.matrix.expand as implementation
    original = implementation.product
    def trap(*args, **kwargs):
        nonlocal called
        called = True
        return original(*args, **kwargs)
    monkeypatch.setattr(implementation, "product", trap)
    with pytest.raises(MatrixCardinalityError):
        expand_matrix(over)
    assert not called
    assert MAX_RAW_CARDINALITY == 100_000


def test_independent_case_execution_is_byte_identical_and_order_independent() -> None:
    plan = _scenario_plan(filters=({"$ne": [
        {"$parameter": "selected"}, {"$literal": 10}
    ]},))
    full = execute_matrix(plan)
    selected = full.cases[-1]
    alone = execute_matrix_case(plan, selected.case_id)
    assert alone.to_json_bytes() == full.results[-1].to_json_bytes()
    assert alone.manifest.run_index == selected.case_index == 2
    reversed_results = {
        case.case_id: execute_matrix_case(plan, case).to_json_bytes()
        for case in reversed(full.cases)
    }
    assert reversed_results == {
        case.case_id: result.to_json_bytes() for case, result in zip(full.cases, full.results)
    }
    assert select_matrix_case(plan, selected.case_id) == selected


def test_matrix_populates_phase_2_1_envelopes_stably_without_host_paths() -> None:
    execution = execute_matrix(_scenario_plan())
    assert isinstance(execution.manifest, MatrixManifest)
    assert isinstance(execution.envelope, MatrixResultEnvelope)
    assert execution.manifest.bounds.original == 3
    assert execution.manifest.bounds.retained == 3
    assert [item.case.case_index for item in execution.manifest.cases] == [0, 1, 2]
    assert canonical_suite_bytes(execution.envelope) == canonical_suite_bytes(execution.envelope)
    assert b"/Users/" not in canonical_suite_bytes(execution.envelope)


def test_composed_suite_identity_is_path_independent(tmp_path: Path) -> None:
    def create(root: Path):
        (root / "mods").mkdir(parents=True)
        (root / "mods/value.yaml").write_text(
            "dsl_version: 1\nmodule: value\nresources:\n  chosen: {input: chosen, required: true}\n",
            encoding="utf-8",
        )
        (root / "root.yaml").write_text("""dsl_version: 1
scenario: composed_matrix
clock: {start: '2026-01-01T00:00:00Z'}
composition:
  modules: {value: mods/value.yaml}
initial_state: {chosen: 0}
steps:
  - id: apply
    write: {chosen: {$resource: value.chosen}}
    transition: null
""", encoding="utf-8")
        return load_composed_suite("root.yaml", composition_root=root)
    left, right = create(tmp_path / "machine-a"), create(tmp_path / "machine-b")
    dimensions = (MatrixDimension("chosen", (4, 5)),)
    first = MatrixPlan(left.root_scenario_identity, left.composed_hash, dimensions, root_seed=7, target=left)
    second = MatrixPlan(right.root_scenario_identity, right.composed_hash, dimensions, root_seed=7, target=right)
    assert first.plan_id == second.plan_id
    assert expand_matrix(first) == expand_matrix(second)
    assert [result.to_json_bytes() for result in execute_matrix(first).results] == [
        result.to_json_bytes() for result in execute_matrix(second).results
    ]


def test_top_level_api_and_package_version_are_unchanged() -> None:
    assert "MatrixPlan" not in scenario_engine.__all__
    assert VERSION == "1.0.0"


def test_static_matrix_package_has_no_nondeterministic_or_unsafe_imports() -> None:
    forbidden = {"random", "secrets", "socket", "subprocess", "importlib", "os", "time", "urllib"}
    for path in (Path(__file__).parents[1] / "src/scenario_engine/matrix").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
            assert not isinstance(node, (ast.Global, ast.Nonlocal))
        assert imported.isdisjoint(forbidden)
