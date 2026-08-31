from __future__ import annotations

from copy import deepcopy
from types import MappingProxyType
from typing import Any, Mapping

from .values import fingerprint


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze(item) for item in value)
    return value


class ScenarioState:
    def __init__(self, initial: Mapping[str, Any] | None = None):
        self._value = deepcopy(dict(initial or {}))

    def snapshot(self) -> Mapping[str, Any]:
        return _freeze(deepcopy(self._value))

    def candidate(self, patch: Mapping[str, Any]) -> dict[str, Any]:
        result = deepcopy(self._value)
        result.update(deepcopy(dict(patch)))
        return result

    def commit(self, candidate: Mapping[str, Any]) -> None:
        self._value = deepcopy(dict(candidate))

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(self._value)

    def fingerprint(self) -> str:
        return fingerprint(self._value)
