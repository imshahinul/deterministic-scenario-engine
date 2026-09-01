"""Deterministic, bounded structured-control primitives for Phase 0.4."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from types import MappingProxyType
from typing import Any, Mapping

from .errors import ScenarioEngineError
from .expressions import EvaluationEnvironment

MAX_REPEAT_COUNT = 100


class ControlFlowError(ScenarioEngineError, ValueError):
    pass


class UnknownSubflowError(ControlFlowError):
    pass


class SubflowCycleError(ControlFlowError):
    pass


class BranchConditionError(ControlFlowError):
    pass


class RepeatCountError(ControlFlowError):
    pass


class RepeatLimitError(ControlFlowError):
    pass


def invocation_component(control_id: str, subflow: str) -> int:
    """Return stable call-site identity in the reserved integer address dimension."""
    payload = f"phase0.4\0{control_id}\0{subflow}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def immutable_scope(values: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(deepcopy(dict(values)))


def evaluate_bindings(bindings, compile_expression, state, resources, scope):
    env = EvaluationEnvironment(state, MappingProxyType({}), MappingProxyType({}), scope)
    return immutable_scope({
        name: compile_expression(bindings[name], resources).evaluate(env)
        for name in sorted(bindings)
    })


def validate_repeat_count(value: Any, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RepeatCountError("repeat count must be a nonnegative integer, not boolean")
    if value > maximum:
        raise RepeatLimitError(f"repeat count {value} exceeds declared max {maximum}")
    return value
