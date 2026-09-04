"""Strict YAML decoding and schema validation for composition documents."""

from __future__ import annotations

from typing import Any, Mapping

import yaml
from yaml.nodes import MappingNode, ScalarNode

from scenario_engine.dsl.errors import DSLParseError
from scenario_engine.dsl.parser import _DSLLoader, _reject_ambiguous_yaml_constructs

from .errors import (
    CompositionDeclarationError,
    CompositionParseError,
    DuplicateModuleAliasError,
    ModuleParseError,
    NestedCompositionError,
)
from .models import valid_alias


ROOT_KEYS = {
    "dsl_version", "scenario", "clock", "initial_state", "steps", "resources",
    "validators", "constraints", "subflows", "invariants", "faults", "oracle",
    "composition",
}
MODULE_KEYS = {
    "dsl_version", "module", "resources", "validators", "constraints", "subflows",
    "invariants", "faults",
}
DECLARATION_SECTIONS = (
    "resources", "validators", "constraints", "subflows", "invariants", "faults",
)


def _strict_load(text: str, *, module: bool) -> Mapping[str, Any]:
    error_type = ModuleParseError if module else CompositionParseError
    try:
        _reject_ambiguous_yaml_constructs(text)
        value = yaml.load(text, Loader=_DSLLoader)
    except DSLParseError:
        if not module and _has_duplicate_module_alias(text):
            raise DuplicateModuleAliasError("composition.modules contains a duplicate alias") from None
        raise error_type("invalid strict YAML document") from None
    except yaml.YAMLError:
        raise error_type("invalid strict YAML document") from None
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise error_type("YAML document root must be a string-keyed mapping")
    _validate_semantic_tree(value, "$", error_type)
    return dict(value)


def _has_duplicate_module_alias(text: str) -> bool:
    """Inspect scalar keys only; construction remains owned by the strict loader."""
    try:
        root = yaml.compose(text, Loader=_DSLLoader)
    except yaml.YAMLError:
        return False
    if not isinstance(root, MappingNode):
        return False

    def child(mapping: MappingNode, name: str) -> Any:
        for key, value in mapping.value:
            if isinstance(key, ScalarNode) and key.value == name:
                return value
        return None

    composition = child(root, "composition")
    if not isinstance(composition, MappingNode):
        return False
    modules = child(composition, "modules")
    if not isinstance(modules, MappingNode):
        return False
    seen: set[str] = set()
    for key, _ in modules.value:
        if not isinstance(key, ScalarNode):
            continue
        if key.value in seen:
            return True
        seen.add(key.value)
    return False


def _validate_semantic_tree(value: Any, path: str, error_type: type[CompositionParseError]) -> None:
    if isinstance(value, float):
        raise error_type(f"{path}: semantic YAML floats are forbidden")
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise error_type(f"{path}: semantic mapping keys must be strings")
        for key in sorted(value):
            _validate_semantic_tree(value[key], f"{path}.{key}", error_type)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _validate_semantic_tree(item, f"{path}[{index}]", error_type)


def parse_composition_root(text: str) -> tuple[dict[str, Any], dict[str, str]]:
    root = dict(_strict_load(text, module=False))
    unknown = sorted(set(root) - ROOT_KEYS)
    if unknown:
        raise CompositionDeclarationError("root contains unknown key(s): " + ", ".join(unknown))
    composition = root.pop("composition", None)
    if composition is None:
        raise CompositionDeclarationError("root composition is required")
    if not isinstance(composition, Mapping) or not all(isinstance(key, str) for key in composition):
        raise CompositionDeclarationError("composition must be a mapping")
    if set(composition) != {"modules"}:
        raise CompositionDeclarationError("composition requires exactly the modules key")
    modules = composition["modules"]
    if not isinstance(modules, Mapping) or not all(isinstance(key, str) for key in modules):
        raise CompositionDeclarationError("composition.modules must be an alias-to-source mapping")
    if not modules:
        raise CompositionDeclarationError("composition.modules must be non-empty")
    declarations: dict[str, str] = {}
    for alias, source in modules.items():
        if not valid_alias(alias):
            raise CompositionDeclarationError("module alias must match [a-z][a-z0-9_]*")
        if not isinstance(source, str) or not source:
            raise CompositionDeclarationError(f"module {alias} source must be a non-empty string")
        declarations[alias] = source
    return root, declarations


def parse_module(text: str, alias: str) -> dict[str, Any]:
    module = dict(_strict_load(text, module=True))
    if "composition" in module:
        raise NestedCompositionError(f"module {alias} cannot declare composition")
    unknown = sorted(set(module) - MODULE_KEYS)
    if unknown:
        raise CompositionDeclarationError(
            f"module {alias} contains unknown key(s): " + ", ".join(unknown)
        )
    if not {"dsl_version", "module"} <= set(module):
        raise CompositionDeclarationError(f"module {alias} requires dsl_version and module")
    if isinstance(module["dsl_version"], bool) or module["dsl_version"] != 1:
        raise CompositionDeclarationError(f"module {alias} dsl_version must be integer 1")
    if not valid_alias(module["module"]):
        raise CompositionDeclarationError(
            f"module {alias} module identity must match [a-z][a-z0-9_]*"
        )
    if module["module"] != alias:
        raise CompositionDeclarationError(
            f"module {alias} identity must equal its composition alias"
        )
    if not any(section in module for section in DECLARATION_SECTIONS):
        raise CompositionDeclarationError(f"module {alias} must contain a declaration section")
    return module
