"""Deterministic external-input and named-resource resolution."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from .values import canonical_bytes, fingerprint, normalize


class ResourceError(ValueError):
    pass


class ResourceResolutionError(ResourceError):
    pass


class ResourceCycleError(ResourceResolutionError):
    pass


def _copy(value: Any) -> Any:
    """Copy a validated semantic tree without invoking arbitrary protocols."""
    normalize(value)
    if isinstance(value, Mapping):
        return {key: _copy(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_copy(item) for item in value]
    return value


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(value[key]) for key in sorted(value)})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _path(text: Any, context: str) -> tuple[str, ...]:
    if not isinstance(text, str) or not text or any(not part for part in text.split(".")):
        raise ResourceResolutionError(f"{context}: expected non-empty dot-separated path")
    return tuple(text.split("."))


def _lookup(value: Any, parts: tuple[str, ...], context: str) -> Any:
    current = value
    for part in parts:
        if not isinstance(current, Mapping) or part not in current:
            raise ResourceResolutionError(f"{context}: missing path segment {part}")
        current = current[part]
    return current


class ResolvedResources:
    def __init__(self, values: Mapping[str, Any], consumed_inputs: Mapping[str, Any] | None = None):
        self._values = _freeze(_copy(values))
        self._consumed = _freeze(_copy(consumed_inputs or {}))

    def lookup(self, path: str) -> Any:
        parts = _path(path, "resource lookup")
        if parts[0] not in self._values:
            raise ResourceResolutionError(f"resource lookup {path}: unknown resource {parts[0]}")
        return _copy(_lookup(self._values[parts[0]], parts[1:], f"resource lookup {path}"))

    def snapshot(self) -> dict[str, Any]:
        return _copy(self._values)

    def normalized(self) -> Any:
        return normalize(self._values)

    def canonical_bytes(self) -> bytes:
        return canonical_bytes(self._values)

    def hashes(self) -> Mapping[str, str]:
        hashes = {f"input:{name}": fingerprint(self._consumed[name]) for name in self._consumed}
        hashes.update({f"resource:{name}": fingerprint(self._values[name]) for name in self._values})
        return MappingProxyType({key: hashes[key] for key in sorted(hashes)})


def _dependencies(node: Any, resource: str) -> set[str]:
    found: set[str] = set()
    if isinstance(node, Mapping):
        if "$ref" in node:
            if len(node) != 1:
                raise ResourceResolutionError(f"resource {resource}: $ref node must contain exactly one operator")
            found.add(_path(node["$ref"], f"resource {resource} $ref")[0])
        elif "$input" in node:
            if len(node) != 1:
                raise ResourceResolutionError(f"resource {resource}: $input node must contain exactly one operator")
            _path(node["$input"], f"resource {resource} $input")
        else:
            for key in sorted(node):
                found.update(_dependencies(node[key], resource))
    elif isinstance(node, (list, tuple)):
        for item in node:
            found.update(_dependencies(item, resource))
    return found


def resolve_resources(
    declarations: Mapping[str, Any], inputs: Mapping[str, Any] | None = None,
) -> ResolvedResources:
    if inputs is None:
        inputs = {}
    if not isinstance(inputs, Mapping) or not all(isinstance(key, str) for key in inputs):
        raise ResourceResolutionError("inputs must be a string-keyed mapping")
    copied_inputs = _copy(inputs)
    names = set(declarations)
    dependencies = {name: _dependencies(declarations[name], name) for name in sorted(names)}
    unknown = sorted(dep for deps in dependencies.values() for dep in deps if dep not in names)
    if unknown:
        raise ResourceResolutionError("unknown referenced resource(s): " + ", ".join(unknown))
    remaining = set(names)
    order: list[str] = []
    while remaining:
        ready = sorted(name for name in remaining if not (dependencies[name] & remaining))
        if not ready:
            raise ResourceCycleError("resource dependency cycle: " + ", ".join(sorted(remaining)))
        order.extend(ready)
        remaining.difference_update(ready)
    resolved: dict[str, Any] = {}
    consumed: dict[str, Any] = {}

    def resolve_node(node: Any, owner: str) -> Any:
        if isinstance(node, Mapping):
            if "$input" in node:
                parts = _path(node["$input"], f"resource {owner} $input")
                if parts[0] not in copied_inputs:
                    raise ResourceResolutionError(
                        f"resource {owner}: unknown external input {'.'.join(parts)}"
                    )
                consumed[parts[0]] = _copy(copied_inputs[parts[0]])
                return _copy(_lookup(copied_inputs[parts[0]], parts[1:],
                                     f"resource {owner} input {'.'.join(parts)}"))
            if "$ref" in node:
                parts = _path(node["$ref"], f"resource {owner} $ref")
                return _copy(_lookup(resolved[parts[0]], parts[1:],
                                     f"resource {owner} reference {'.'.join(parts)}"))
            return {key: resolve_node(node[key], owner) for key in sorted(node)}
        if isinstance(node, (list, tuple)):
            return [resolve_node(item, owner) for item in node]
        return _copy(node)

    for name in order:
        resolved[name] = resolve_node(declarations[name], name)
    return ResolvedResources(resolved, consumed)
