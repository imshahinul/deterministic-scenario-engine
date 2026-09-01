"""Pure deterministic resource validators and pre-execution constraints."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Mapping

from .errors import ScenarioEngineError
from .expressions import EvaluationEnvironment, Expression
from .ids import LogicalID
from .resources import ResolvedResources, ResourceResolutionError
from .values import MISSING, canonical_bytes


class ResourceValidationError(ScenarioEngineError, ValueError):
    pass


class ConstraintError(ScenarioEngineError, ValueError):
    pass


class ConstraintDefinitionError(ConstraintError):
    pass


class ConstraintViolation(ConstraintError):
    pass


def semantic_equal(left: Any, right: Any) -> bool:
    return canonical_bytes(left) == canonical_bytes(right)


def _semantic_type(value: Any) -> str:
    if value is MISSING: return "missing"
    if value is None: return "null"
    if type(value) is bool: return "boolean"
    if type(value) is int: return "integer"
    if isinstance(value, Decimal): return "decimal"
    if isinstance(value, str): return "string"
    if isinstance(value, datetime): return "datetime"
    if isinstance(value, timedelta): return "duration"
    if isinstance(value, LogicalID): return "logical_id"
    if isinstance(value, (list, tuple)): return "list"
    if isinstance(value, Mapping): return "map"
    return "unsupported"


def validate_resources(resources: ResolvedResources, declarations: tuple[Mapping[str, Any], ...]) -> None:
    for declaration in declarations:
        validator_id = declaration["id"]
        path = declaration["resource"]
        kind = declaration["kind"]
        try:
            value = resources.lookup(path)
        except ResourceResolutionError as error:
            raise ResourceValidationError(
                f"validator {validator_id} ({kind}) resource {path}: {error}"
            ) from None
        reason: str | None = None
        if kind == "required":
            if value is MISSING: reason = "value is MISSING"
        elif kind == "type":
            actual = _semantic_type(value)
            if actual != declaration["type"]: reason = f"expected {declaration['type']}, got {actual}"
        elif kind == "range":
            if type(value) not in (int, Decimal): reason = "value is not integer or decimal"
            else:
                if "min" in declaration and Decimal(value) < Decimal(declaration["min"]): reason = "below inclusive minimum"
                if "max" in declaration and Decimal(value) > Decimal(declaration["max"]): reason = "above inclusive maximum"
        elif kind == "length":
            if not isinstance(value, (str, list, tuple, Mapping)): reason = "value has no supported length"
            else:
                if "min" in declaration and len(value) < declaration["min"]: reason = "below inclusive minimum length"
                if "max" in declaration and len(value) > declaration["max"]: reason = "above inclusive maximum length"
        elif kind == "one_of":
            if not any(semantic_equal(value, candidate) for candidate in declaration["values"]):
                reason = "value is not one of allowed semantic values"
        if reason:
            raise ResourceValidationError(
                f"validator {validator_id} ({kind}) resource {path}: {reason}"
            )


def evaluate_constraints(constraints: tuple[tuple[str, Expression, str | None], ...]) -> None:
    environment = EvaluationEnvironment({}, {}, {})
    for constraint_id, expression, message in constraints:
        result = expression.evaluate(environment)
        if type(result) is not bool:
            raise ConstraintDefinitionError(f"constraint {constraint_id}: check must return boolean")
        if not result:
            suffix = f": {message}" if message else ""
            raise ConstraintViolation(f"constraint {constraint_id} violated{suffix}")
