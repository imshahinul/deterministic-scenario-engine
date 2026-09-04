"""Secure depth-one resolver and deterministic namespace composer."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Any, Mapping

from scenario_engine.canonical import canonical_scenario_payload
from scenario_engine.dsl import compile_document, parse_yaml
from scenario_engine.dsl.errors import DSLError
from scenario_engine.suite import SuiteManifest
from scenario_engine.values import canonical_bytes

from .canonical import composed_suite_hash, module_content_hash, semantic_declaration_payload
from .errors import (
    CompositionBoundError,
    CompositionDeclarationError,
    CompositionPathError,
    CompositionRootEscapeError,
    CompositionSymlinkError,
    ModuleFileTypeError,
    ModuleNotFoundError,
    ModuleParseError,
    NamespaceCollisionError,
    UnsupportedCompositionSourceError,
)
from .models import (
    COMPOSITION_CONTRACT_VERSION,
    MAX_AGGREGATE_INPUT_BYTES,
    MAX_CANONICAL_COMPOSED_BYTES,
    MAX_MODULE_DOCUMENT_BYTES,
    MAX_MODULES,
    MAX_ROOT_DOCUMENT_BYTES,
    ComposedSuite,
    ModuleIdentity,
)
from .parser import DECLARATION_SECTIONS, parse_composition_root, parse_module


_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:")


def _read_bounded(path: Path, limit: int, label: str) -> tuple[str, int]:
    try:
        size = path.stat().st_size
    except OSError:
        raise ModuleNotFoundError(f"{label} does not exist") from None
    if size > limit:
        raise CompositionBoundError(f"{label} exceeds {limit} bytes")
    try:
        data = path.read_bytes()
    except OSError:
        raise CompositionPathError(f"unable to read {label}") from None
    if len(data) > limit:
        raise CompositionBoundError(f"{label} exceeds {limit} bytes")
    try:
        return data.decode("utf-8"), len(data)
    except UnicodeDecodeError:
        raise ModuleParseError(f"{label} must be UTF-8") from None


def _root(root: str | Path) -> Path:
    value = Path(root)
    if not value.is_absolute():
        raise CompositionPathError("composition root must be an explicit absolute path")
    try:
        if value.is_symlink():
            raise CompositionSymlinkError("composition root cannot be a symlink")
        resolved = value.resolve(strict=True)
    except CompositionSymlinkError:
        raise
    except OSError:
        raise CompositionPathError("composition root does not exist") from None
    if not resolved.is_dir():
        raise CompositionPathError("composition root must be a directory")
    return resolved


def _validate_source(source: str, alias: str) -> tuple[str, ...]:
    if "\x00" in source or "\\" in source:
        raise CompositionPathError(f"module {alias} source contains a forbidden character")
    lowered = source.lower()
    if lowered.startswith(("http://", "https://", "ftp://", "file://", "git://", "git+")):
        raise UnsupportedCompositionSourceError(f"module {alias} source URI is forbidden")
    if _SCHEME.match(source):
        raise UnsupportedCompositionSourceError(f"module {alias} source scheme is forbidden")
    raw_parts = source.split("/")
    path = PurePosixPath(source)
    parts = path.parts
    if source.startswith("/") or not parts or any(part in {"", ".", ".."} for part in raw_parts):
        raise CompositionRootEscapeError(f"module {alias} source must remain beneath the composition root")
    return parts


def _secure_relative(root: Path, parts: tuple[str, ...], label: str) -> Path:
    current = root
    for part in parts:
        current = current / part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            raise ModuleNotFoundError(f"{label} does not exist") from None
        except OSError:
            raise CompositionPathError(f"unable to inspect {label}") from None
        if stat.S_ISLNK(mode):
            raise CompositionSymlinkError(f"{label} contains a symlink")
    try:
        resolved = current.resolve(strict=True)
        resolved.relative_to(root)
    except ValueError:
        raise CompositionRootEscapeError(f"{label} escapes the composition root") from None
    except OSError:
        raise ModuleNotFoundError(f"{label} does not exist") from None
    if not resolved.is_file() or not stat.S_ISREG(resolved.stat().st_mode):
        raise ModuleFileTypeError(f"{label} must be a regular file")
    return resolved


def _root_file(root: Path, root_file: str | Path) -> Path:
    value = Path(root_file)
    try:
        relative = value.relative_to(root) if value.is_absolute() else value
    except ValueError:
        raise CompositionRootEscapeError("root scenario must be beneath the composition root") from None
    parts = relative.parts
    if not parts or any(part in {"", ".", ".."} for part in parts) or relative.is_absolute():
        raise CompositionPathError("root scenario path is invalid")
    return _secure_relative(root, parts, "root scenario")


def _qualified(alias: str, value: Any, aliases: set[str]) -> Any:
    if not isinstance(value, str) or not value:
        return value
    first = value.split(".", 1)[0]
    return value if first in aliases else f"{alias}.{value}"


def _physical_resource(alias: str, name: str) -> str:
    return f"@composition:{alias}:{name}"


def _resource_reference(value: Any, alias: str, aliases: set[str]) -> Any:
    if not isinstance(value, str) or not value:
        return value
    parts = value.split(".")
    owner = alias
    if parts[0] in aliases:
        owner = parts.pop(0)
    if not parts:
        return value
    return ".".join((_physical_resource(owner, parts[0]), *parts[1:]))


def _references(
    value: Any, alias: str, aliases: set[str], *, resource_declaration: bool = False,
) -> Any:
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if key == "$ref" and resource_declaration:
                result[key] = _resource_reference(item, alias, aliases)
            elif key == "$resource":
                result[key] = _qualified(alias, item, aliases)
            else:
                result[key] = _references(
                    item, alias, aliases, resource_declaration=resource_declaration,
                )
        return result
    if isinstance(value, list):
        return [
            _references(item, alias, aliases, resource_declaration=resource_declaration)
            for item in value
        ]
    return value


def _nodes(nodes: Any, alias: str, aliases: set[str]) -> Any:
    if not isinstance(nodes, list):
        return nodes
    result = []
    for raw in nodes:
        if not isinstance(raw, Mapping):
            result.append(raw)
            continue
        node = _references(raw, alias, aliases)
        if "id" in node:
            node["id"] = _qualified(alias, node["id"], aliases)
        if node.get("transition") is not None:
            node["transition"] = _qualified(alias, node["transition"], aliases)
        for control in ("call", "repeat"):
            if isinstance(node.get(control), Mapping) and "subflow" in node[control]:
                node[control]["subflow"] = _qualified(alias, node[control]["subflow"], aliases)
        branch = node.get("branch")
        if isinstance(branch, Mapping):
            for case in branch.get("cases", ()) if isinstance(branch.get("cases", ()), list) else ():
                if isinstance(case, dict) and "subflow" in case:
                    case["subflow"] = _qualified(alias, case["subflow"], aliases)
            otherwise = branch.get("else")
            if isinstance(otherwise, dict) and "subflow" in otherwise:
                otherwise["subflow"] = _qualified(alias, otherwise["subflow"], aliases)
        result.append(node)
    return result


def _namespace_module(module: Mapping[str, Any], alias: str, aliases: set[str]) -> dict[str, Any]:
    namespaced: dict[str, Any] = {}
    resources = module.get("resources")
    if resources is not None:
        if isinstance(resources, Mapping):
            # Resource lookup already treats dots as semantic path separators.
            # A namespace is therefore one root resource containing declarations,
            # making `alias.name` resolve without changing the v1 resolver.
            namespaced["resources"] = {
                **{
                    _physical_resource(alias, name): _references(
                        value, alias, aliases, resource_declaration=True,
                    )
                    for name, value in resources.items()
                },
                alias: {
                    name: {"$ref": _physical_resource(alias, name)}
                    for name in resources
                },
            }
        else:
            namespaced["resources"] = resources
    subflows = module.get("subflows")
    if subflows is not None:
        if isinstance(subflows, Mapping):
            namespaced["subflows"] = {
                f"{alias}.{name}": {
                    **dict(value),
                    "steps": _nodes(value.get("steps"), alias, aliases),
                } if isinstance(value, Mapping) else value
                for name, value in subflows.items()
            }
        else:
            namespaced["subflows"] = subflows
    validators = module.get("validators")
    if validators is not None:
        namespaced["validators"] = [] if isinstance(validators, list) else validators
        if isinstance(validators, list):
            for raw in validators:
                item = _references(raw, alias, aliases)
                if isinstance(item, dict):
                    if "id" in item: item["id"] = _qualified(alias, item["id"], aliases)
                    if "resource" in item: item["resource"] = _qualified(alias, item["resource"], aliases)
                namespaced["validators"].append(item)
    for section in ("constraints", "invariants"):
        values = module.get(section)
        if values is not None:
            namespaced[section] = [] if isinstance(values, list) else values
            if isinstance(values, list):
                for raw in values:
                    item = _references(raw, alias, aliases)
                    if isinstance(item, dict) and "id" in item:
                        item["id"] = _qualified(alias, item["id"], aliases)
                    namespaced[section].append(item)
    faults = module.get("faults")
    if faults is not None:
        namespaced["faults"] = [] if isinstance(faults, list) else faults
        if isinstance(faults, list):
            for raw in faults:
                item = _references(raw, alias, aliases)
                if isinstance(item, dict):
                    if "id" in item: item["id"] = _qualified(alias, item["id"], aliases)
                    selector = item.get("selector")
                    if isinstance(selector, dict) and "step" in selector:
                        selector["step"] = _qualified(alias, selector["step"], aliases)
                    expect = item.get("expect")
                    if isinstance(expect, dict):
                        for kind in ("constraints", "invariants"):
                            if isinstance(expect.get(kind), list):
                                expect[kind] = [_qualified(alias, value, aliases) for value in expect[kind]]
                    operator = item.get("operator")
                    if isinstance(operator, dict) and isinstance(operator.get("override_resource"), dict):
                        body = operator["override_resource"]
                        if "path" in body: body["path"] = _qualified(alias, body["path"], aliases)
                namespaced["faults"].append(item)
    return namespaced


def _merge(root: dict[str, Any], modules: list[tuple[str, Mapping[str, Any]]]) -> dict[str, Any]:
    result = json.loads(json.dumps(root, ensure_ascii=False))
    aliases = {alias for alias, _ in modules}
    for section in ("resources", "subflows"):
        declarations = result.get(section, {})
        if not isinstance(declarations, Mapping):
            continue
        for name in declarations:
            if name.startswith("@composition:"):
                raise NamespaceCollisionError(
                    f"{section} root declaration uses a reserved composition coordinate"
                )
            if any(name == alias or name.startswith(alias + ".") for alias in aliases):
                raise NamespaceCollisionError(
                    f"{section} root declaration collides with module namespace: {name}"
                )
    for alias, module in modules:
        additions = _namespace_module(module, alias, aliases)
        for section in DECLARATION_SECTIONS:
            if section not in additions:
                continue
            value = additions[section]
            if section in {"resources", "subflows"}:
                if not isinstance(value, Mapping):
                    result[section] = value
                    continue
                existing = result.setdefault(section, {})
                if not isinstance(existing, dict):
                    continue
                collisions = sorted(set(existing) & set(value))
                if collisions:
                    raise NamespaceCollisionError(
                        f"{section} declaration collision: {collisions[0]}"
                    )
                existing.update(value)
            else:
                if not isinstance(value, list):
                    result[section] = value
                    continue
                existing = result.setdefault(section, [])
                if not isinstance(existing, list):
                    continue
                existing_ids = {
                    item.get("id") for item in existing if isinstance(item, Mapping)
                }
                for item in value:
                    if isinstance(item, Mapping) and item.get("id") in existing_ids:
                        raise NamespaceCollisionError(
                            f"{section} declaration collision: {item.get('id')}"
                        )
                    if isinstance(item, Mapping): existing_ids.add(item.get("id"))
                    existing.append(item)
    return result


def load_composed_suite(
    root_file: str | Path, *, composition_root: str | Path,
) -> ComposedSuite:
    """Resolve one root and its depth-one local modules beneath an explicit root."""
    allowed_root = _root(composition_root)
    root_path = _root_file(allowed_root, root_file)
    root_text, aggregate = _read_bounded(root_path, MAX_ROOT_DOCUMENT_BYTES, "root scenario")
    root_raw, declarations = parse_composition_root(root_text)
    if len(declarations) > MAX_MODULES:
        raise CompositionBoundError(f"composition exceeds {MAX_MODULES} modules")
    spellings: dict[str, str] = {}
    loaded: list[tuple[str, Mapping[str, Any]]] = []
    identities: list[ModuleIdentity] = []
    for alias in sorted(declarations):
        source = declarations[alias]
        folded = source.casefold()
        if folded in spellings and spellings[folded] != source:
            raise CompositionPathError("module source spellings collide under case-folding")
        spellings[folded] = source
        parts = _validate_source(source, alias)
        path = _secure_relative(allowed_root, parts, f"module {alias}")
        text, size = _read_bounded(path, MAX_MODULE_DOCUMENT_BYTES, f"module {alias}")
        aggregate += size
        if aggregate > MAX_AGGREGATE_INPUT_BYTES:
            raise CompositionBoundError(
                f"composition input exceeds {MAX_AGGREGATE_INPUT_BYTES} bytes"
            )
        module = parse_module(text, alias)
        declarations_payload = {
            section: module[section]
            for section in DECLARATION_SECTIONS
            if section in module
        }
        semantic = semantic_declaration_payload(declarations_payload)
        identity = ModuleIdentity(alias, module_content_hash(declarations_payload), semantic)
        identities.append(identity)
        loaded.append((alias, module))
    try:
        root_document = parse_yaml(json.dumps(root_raw, ensure_ascii=False))
        root_payload = canonical_scenario_payload(root_document)
        merged_document = parse_yaml(json.dumps(_merge(root_raw, loaded), ensure_ascii=False))
        compiled = compile_document(merged_document)
    except DSLError as error:
        raise CompositionDeclarationError(f"resolved DSL 1 scenario is invalid: {error}") from None
    identities_tuple = tuple(identities)
    composed_hash = composed_suite_hash(root_payload, identities_tuple)
    canonical_size = len(canonical_bytes({
        "contract_version": COMPOSITION_CONTRACT_VERSION,
        "root": root_payload,
        "modules": [
            {"alias": item.alias, "content_hash": item.content_hash, "payload": item.payload}
            for item in identities_tuple
        ],
    }))
    if canonical_size > MAX_CANONICAL_COMPOSED_BYTES:
        raise CompositionBoundError(
            f"canonical composition exceeds {MAX_CANONICAL_COMPOSED_BYTES} bytes"
        )
    manifest = SuiteManifest(
        root_scenario_identity=merged_document.scenario_id,
        composed_hash=composed_hash,
        composition_contract_version=COMPOSITION_CONTRACT_VERSION,
        module_hashes={item.alias: item.content_hash for item in identities_tuple},
    )
    return ComposedSuite(
        merged_document.scenario_id, root_payload, identities_tuple, composed_hash,
        merged_document, compiled, manifest,
    )
