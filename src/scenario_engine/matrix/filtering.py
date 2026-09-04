"""Restricted, pure matrix-filter expression evaluation."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping

from scenario_engine.values import canonical_bytes

from .errors import MatrixFilterError


_BINARY = {"$eq", "$ne", "$lt", "$lte", "$gt", "$gte"}


def _ordered(left: Any, right: Any) -> tuple[Any, Any]:
    from datetime import datetime
    numeric = lambda value: not isinstance(value, bool) and isinstance(value, (int, Decimal))
    if numeric(left) and numeric(right):
        return Decimal(left), Decimal(right)
    if isinstance(left, str) and isinstance(right, str):
        return left, right
    if isinstance(left, datetime) and isinstance(right, datetime):
        if left.tzinfo is None or right.tzinfo is None:
            raise MatrixFilterError("filter ordering datetimes must be timezone-aware")
        return left, right
    raise MatrixFilterError("filter ordering operands have incompatible semantic types")


def evaluate_filter(expression: Mapping[str, Any], assignment: Mapping[str, Any]) -> bool:
    """Evaluate the frozen data-only expression subset over parameters alone."""
    value = _evaluate(expression, assignment)
    if type(value) is not bool:
        raise MatrixFilterError("matrix filter must evaluate to exact boolean")
    return value


def _evaluate(expression: Any, assignment: Mapping[str, Any]) -> Any:
    if not isinstance(expression, Mapping) or len(expression) != 1:
        raise MatrixFilterError("filter expression must contain exactly one operator")
    operator, payload = next(iter(expression.items()))
    if operator == "$literal":
        return payload
    if operator == "$parameter":
        if not isinstance(payload, str) or payload not in assignment:
            raise MatrixFilterError("filter references an unknown parameter")
        return assignment[payload]
    if operator in _BINARY:
        if not isinstance(payload, (tuple, list)) or len(payload) != 2:
            raise MatrixFilterError(f"{operator} requires two operands")
        left, right = (_evaluate(payload[0], assignment), _evaluate(payload[1], assignment))
        if operator in {"$eq", "$ne"}:
            equal = canonical_bytes(left) == canonical_bytes(right)
            return equal if operator == "$eq" else not equal
        left, right = _ordered(left, right)
        return {"$lt": left < right, "$lte": left <= right,
                "$gt": left > right, "$gte": left >= right}[operator]
    if operator in {"$and", "$or"}:
        if not isinstance(payload, (tuple, list)) or not payload:
            raise MatrixFilterError(f"{operator} requires a nonempty operand sequence")
        values = tuple(_evaluate(item, assignment) for item in payload)
        if any(type(item) is not bool for item in values):
            raise MatrixFilterError(f"{operator} operands must be boolean")
        return all(values) if operator == "$and" else any(values)
    if operator == "$not":
        value = _evaluate(payload, assignment)
        if type(value) is not bool:
            raise MatrixFilterError("$not operand must be boolean")
        return not value
    raise MatrixFilterError(f"unsupported matrix filter operator: {operator}")
