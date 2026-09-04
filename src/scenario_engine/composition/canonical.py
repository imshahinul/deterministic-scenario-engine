"""Canonical alias/content and composed-suite identity."""

from __future__ import annotations

import hashlib
from typing import Any, Mapping

from scenario_engine.dsl import decode_semantic_value
from scenario_engine.values import canonical_bytes, normalize

from .models import COMPOSITION_CONTRACT_VERSION, ComposedSuite, ModuleIdentity


_SEMANTIC_WRAPPERS = {"$decimal", "$datetime", "$duration", "$missing"}


def semantic_declaration_payload(value: Any) -> Any:
    """Normalize YAML declarations while preserving significant sequence order."""
    if isinstance(value, Mapping):
        if len(value) == 1 and next(iter(value)) in _SEMANTIC_WRAPPERS:
            return decode_semantic_value(value)
        if len(value) == 1 and "$literal" in value:
            return {"$literal": decode_semantic_value(value["$literal"])}
        return {key: semantic_declaration_payload(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [semantic_declaration_payload(item) for item in value]
    if isinstance(value, float):
        raise TypeError("semantic YAML floats are forbidden")
    return value


def module_content_hash(payload: Mapping[str, Any]) -> str:
    """Hash a module's canonical semantic declaration payload."""
    return hashlib.sha256(canonical_bytes(semantic_declaration_payload(payload))).hexdigest()


def composition_payload(
    root_payload: Mapping[str, Any], modules: tuple[ModuleIdentity, ...],
) -> Mapping[str, Any]:
    return normalize({
        "contract_version": COMPOSITION_CONTRACT_VERSION,
        "root": root_payload,
        "modules": [
            {"alias": item.alias, "content_hash": item.content_hash, "payload": item.payload}
            for item in sorted(modules, key=lambda item: item.alias)
        ],
    })


def canonical_composition_bytes(value: ComposedSuite) -> bytes:
    """Return path-free canonical bytes committed to by the composed hash."""
    if not isinstance(value, ComposedSuite):
        raise TypeError("value must be a ComposedSuite")
    return canonical_bytes(composition_payload(value.root_payload, value.modules))


def composed_suite_hash(
    root_payload: Mapping[str, Any], modules: tuple[ModuleIdentity, ...],
) -> str:
    return hashlib.sha256(canonical_bytes(composition_payload(root_payload, modules))).hexdigest()
