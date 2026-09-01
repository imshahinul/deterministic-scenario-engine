"""Local Schemathesis Case binding without request execution."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

from scenario_engine.errors import ScenarioEngineError

try:
    import schemathesis  # noqa: F401 - verifies the explicit optional dependency
    from hypothesis import strategies as st
    from hypothesis.strategies import SearchStrategy
except ImportError as error:  # pragma: no cover - dependency-isolation subprocesses
    raise ImportError(
        "scenario_engine.integrations.schemathesis requires the optional "
        "'schemathesis' extra (hypothesis>=6,<7 and schemathesis>=4,<5)"
    ) from error

from scenario_engine.integrations.hypothesis import ScenarioHypothesisCase
from scenario_engine.result import ScenarioResult


class SchemathesisIntegrationError(ScenarioEngineError, ValueError):
    """Base error for explicit Schemathesis composition failures."""


class ScenarioBindingError(SchemathesisIntegrationError):
    """A binding path or destination container is invalid."""


class UnsupportedHTTPBindingValueError(ScenarioBindingError):
    """A path, query, or header binding is not an HTTP scalar."""


def _frozen_mapping(value: Mapping[str, str]) -> Mapping[str, str]:
    if not isinstance(value, Mapping) or not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
        raise ScenarioBindingError("binding groups must map string destinations to string source paths")
    return MappingProxyType({key: value[key] for key in sorted(value)})


@dataclass(frozen=True, slots=True)
class SchemathesisCaseBindings:
    path_parameters: Mapping[str, str] = field(default_factory=dict)
    query: Mapping[str, str] = field(default_factory=dict)
    headers: Mapping[str, str] = field(default_factory=dict)
    body: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("path_parameters", "query", "headers", "body"):
            object.__setattr__(self, name, _frozen_mapping(getattr(self, name)))


@dataclass(frozen=True, slots=True)
class BoundSchemathesisCase:
    case: Any
    scenario: ScenarioHypothesisCase


def _resolve(tree: Mapping[str, Any], path: str) -> Any:
    if not path:
        raise ScenarioBindingError("binding source path must not be empty")
    value: Any = tree
    for component in path.split("."):
        if isinstance(value, Mapping):
            if component not in value:
                raise ScenarioBindingError(f"binding source path not found: {path}")
            value = value[component]
        elif isinstance(value, list) and component.isdecimal():
            index = int(component)
            if index >= len(value):
                raise ScenarioBindingError(f"binding source path not found: {path}")
            value = value[index]
        else:
            raise ScenarioBindingError(f"binding source path not found: {path}")
    return deepcopy(value)


def bind_case(case: Any, result: ScenarioResult, bindings: SchemathesisCaseBindings) -> Any:
    """Overlay selected normalized values while preserving generated values."""
    if not isinstance(result, ScenarioResult):
        raise ScenarioBindingError("result must be a ScenarioResult")
    source = result.normalized()
    for group_name in ("path_parameters", "query", "headers"):
        group = getattr(bindings, group_name)
        existing = getattr(case, group_name, None)
        if existing is None:
            container: dict[str, Any] = {}
        elif isinstance(existing, Mapping):
            container = deepcopy(dict(existing))
        else:
            raise ScenarioBindingError(f"case {group_name} must be a mapping or None")
        for destination, path in group.items():
            value = _resolve(source, path)
            if value is None or isinstance(value, (dict, list)) or type(value) not in (str, int, bool):
                raise UnsupportedHTTPBindingValueError(
                    f"{group_name}.{destination} requires a non-null string, integer, or boolean"
                )
            container[destination] = value
        setattr(case, group_name, container)

    if bindings.body:
        existing_body = getattr(case, "body", None)
        if existing_body is None:
            body: dict[str, Any] = {}
        elif isinstance(existing_body, Mapping) and all(isinstance(key, str) for key in existing_body):
            body = deepcopy(dict(existing_body))
        else:
            raise ScenarioBindingError("case body must be a string-keyed mapping or None")
        for destination, path in bindings.body.items():
            body[destination] = _resolve(source, path)
        case.body = body
    return case


def operation_cases(
    operation: Any,
    scenario_strategy: SearchStrategy[ScenarioHypothesisCase],
    bindings: SchemathesisCaseBindings,
) -> SearchStrategy[BoundSchemathesisCase]:
    """Compose public operation generation with deterministic scenario draws."""
    if not hasattr(operation, "as_strategy") or not isinstance(scenario_strategy, SearchStrategy):
        raise SchemathesisIntegrationError("operation and scenario strategy are invalid")
    operation_strategy = operation.as_strategy()
    if not isinstance(operation_strategy, SearchStrategy):
        raise SchemathesisIntegrationError("operation.as_strategy() did not return a SearchStrategy")
    return st.tuples(operation_strategy, scenario_strategy).map(
        lambda pair: BoundSchemathesisCase(bind_case(pair[0], pair[1].result, bindings), pair[1])
    )


__all__ = [
    "BoundSchemathesisCase",
    "ScenarioBindingError",
    "SchemathesisCaseBindings",
    "SchemathesisIntegrationError",
    "UnsupportedHTTPBindingValueError",
    "bind_case",
    "operation_cases",
]
