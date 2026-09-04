"""Bounded ordered Cartesian expansion and stable case selection."""

from __future__ import annotations

from itertools import product

from scenario_engine.suite import MatrixCase
from scenario_engine.values import canonical_bytes

from .canonical import stable_case_id
from .errors import (
    DuplicateMatrixCaseError, MatrixCardinalityError, MatrixCaseNotFoundError,
)
from .filtering import evaluate_filter
from .models import MAX_RAW_CARDINALITY, MAX_RETAINED_CASES, MatrixPlan


def raw_cardinality(plan: MatrixPlan) -> int:
    """Check the pre-filter product without materializing candidates."""
    if not isinstance(plan, MatrixPlan):
        raise TypeError("plan must be a MatrixPlan")
    cardinality = 1
    for dimension in plan.dimensions:
        count = len(dimension.values)
        if cardinality > MAX_RAW_CARDINALITY // count:
            raise MatrixCardinalityError(
                f"matrix pre-filter cardinality exceeds {MAX_RAW_CARDINALITY}"
            )
        cardinality *= count
    return cardinality


def expand_matrix(plan: MatrixPlan) -> tuple[MatrixCase, ...]:
    """Expand in odometer order, assigning raw indexes before filters."""
    raw_cardinality(plan)
    value_axes = tuple(item.values for item in plan.dimensions)
    combinations = product(*value_axes) if value_axes else ((),)
    retained: list[MatrixCase] = []
    seen: set[bytes] = set()
    names = tuple(item.name for item in plan.dimensions)
    for case_index, values in enumerate(combinations):
        assignment = {name: value for name, value in zip(names, values)}
        identity = canonical_bytes(assignment)
        if identity in seen:
            raise DuplicateMatrixCaseError(
                "matrix contains duplicate canonical assignments at distinct positions"
            )
        seen.add(identity)
        if not all(evaluate_filter(item, assignment) for item in plan.filters):
            continue
        if len(retained) >= MAX_RETAINED_CASES:
            raise MatrixCardinalityError(
                f"matrix retained cases exceed {MAX_RETAINED_CASES}"
            )
        case_id = stable_case_id(plan.suite_hash, case_index, assignment)
        retained.append(MatrixCase(case_index, case_id, assignment, case_id))
    return tuple(retained)


def select_matrix_case(plan: MatrixPlan, case_id: str) -> MatrixCase:
    """Resolve one retained case by stable ID without running preceding cases."""
    if not isinstance(case_id, str):
        raise TypeError("case_id must be a string")
    for case in expand_matrix(plan):
        if case.case_id == case_id:
            return case
    raise MatrixCaseNotFoundError("matrix case identity was not retained by this plan")
