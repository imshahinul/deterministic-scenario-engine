from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from scenario_engine.ids import LogicalID
from scenario_engine.plugins import GeneratorPlugin, PluginRegistry
from scenario_engine.suite import DomainPackRecord
from scenario_engine.values import MISSING
from scenario_engine.domain_packs import (
    MAX_ASSETS_PER_PACK,
    MAX_PACKS_PER_REGISTRY,
    DomainPack,
    DomainPackBoundError,
    DomainPackCollisionError,
    DomainPackDefinitionError,
    DomainPackNotFoundError,
    DomainPackRegistry,
    PluginRequirement,
    canonical_domain_pack_bytes,
)


def _pack(**changes):
    values = {
        "name": "example.commerce",
        "version": "2026.1",
        "resource_templates": {
            "order": {
                "missing": MISSING,
                "nothing": None,
                "flag": True,
                "count": 1,
                "money": Decimal("12.30"),
                "id": LogicalID("00000000-0000-0000-0000-000000000001"),
                "at": datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
                "ordered": ["a", "b"],
            }
        },
        "validators": {"positive": {"operator": "gt", "value": 0}},
        "documentation": {"summary": "portable semantics"},
    }
    values.update(changes)
    return DomainPack(**values)


def test_model_is_immutable_and_isolates_caller_mutation():
    source = {"asset": {"nested": [1, 2]}}
    pack = _pack(resource_templates=source)
    source["asset"]["nested"].append(3)
    assert pack.resource_templates["asset"]["nested"] == (1, 2)
    with pytest.raises(TypeError):
        pack.resource_templates["asset"] = {}  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        pack.version = "changed"  # type: ignore[misc]


def test_canonical_identity_is_repeatable_equivalent_typed_and_path_independent(tmp_path):
    first = _pack()
    equivalent = _pack(
        resource_templates=dict(reversed(list(first.resource_templates.items()))),
        validators=dict(reversed(list(first.validators.items()))),
    )
    assert canonical_domain_pack_bytes(first) == canonical_domain_pack_bytes(first)
    assert first.content_hash == equivalent.content_hash
    assert b"$type" in first.canonical_bytes()
    changed = _pack(documentation={"summary": "changed"})
    assert changed.content_hash != first.content_hash
    checkout_a = tmp_path / "checkout-a"
    checkout_b = tmp_path / "checkout-b"
    assert str(checkout_a).encode() not in first.canonical_bytes()
    assert str(checkout_b).encode() not in first.canonical_bytes()


@pytest.mark.parametrize("name", ["commerce", "Example.commerce", "example-commerce", "a..b", ""])
def test_malformed_names_fail(name):
    with pytest.raises(DomainPackDefinitionError):
        _pack(name=name)


@pytest.mark.parametrize("version", ["", " 1", "1 ", "a\nb", "☃"])
def test_malformed_versions_fail(version):
    with pytest.raises(DomainPackDefinitionError):
        _pack(version=version)


def test_explicit_registry_exact_resolution_order_not_found_and_collisions():
    alpha = _pack(name="example.alpha")
    zeta = _pack(name="example.zeta")
    registry = DomainPackRegistry([zeta, alpha])
    assert tuple(item.name for item in registry) == ("example.alpha", "example.zeta")
    assert registry.resolve("example.alpha", "2026.1") is alpha
    assert registry.resolve_all(((zeta.name, zeta.version), (alpha.name, alpha.version))) == (
        alpha,
        zeta,
    )
    with pytest.raises(DomainPackNotFoundError, match="example.missing@1"):
        registry.resolve("example.missing", "1")
    with pytest.raises(DomainPackCollisionError):
        DomainPackRegistry([alpha, alpha])
    with pytest.raises(DomainPackCollisionError):
        DomainPackRegistry([alpha, _pack(name=alpha.name, version="2026.2")])
    with pytest.raises(DomainPackCollisionError):
        registry.resolve_all(((alpha.name, alpha.version), (alpha.name, alpha.version)))


def test_suite_record_is_exact_repeatable_and_contains_no_host_path(tmp_path):
    pack = _pack()
    record = pack.to_record()
    assert isinstance(record, DomainPackRecord)
    assert record == DomainPackRecord(pack.name, pack.version, pack.content_hash)
    assert record == pack.to_record()
    assert str(tmp_path) not in repr(record)


def test_plugin_reference_remains_declarative_and_requires_explicit_registry():
    requirement = PluginRequirement("example.generator", "1")
    pack = _pack(plugin_requirements=(requirement,))
    assert pack.plugin_requirements == (requirement,)
    registry = DomainPackRegistry((pack,))
    with pytest.raises(TypeError):
        registry.validate_plugins(pack)  # type: ignore[call-arg]
    explicit = PluginRegistry((GeneratorPlugin("example.generator", "1", lambda context, args: 1),))
    registry.validate_plugins(pack, explicit)


def test_composition_boundary_is_typed_declarative_and_has_reserved_sections_only():
    assets = _pack().composition_assets()
    assert tuple(assets) == (
        "constraints",
        "documentation",
        "oracle_fragments",
        "resource_templates",
        "validators",
    )
    with pytest.raises(TypeError):
        assets["other"] = {}  # type: ignore[index]


def test_asset_exact_bound_and_one_over_rejection():
    exact = {f"item_{index:05d}": None for index in range(MAX_ASSETS_PER_PACK)}
    assert len(
        _pack(
            resource_templates=exact,
            validators={},
            constraints={},
            oracle_fragments={},
            documentation={},
        ).resource_templates
    ) == MAX_ASSETS_PER_PACK
    exact["over"] = None
    with pytest.raises(DomainPackBoundError):
        _pack(
            resource_templates=exact,
            validators={},
            constraints={},
            oracle_fragments={},
            documentation={},
        )


def test_registry_exact_bound_and_one_over_rejection():
    packs = [DomainPack(f"example.p{index}", "1") for index in range(MAX_PACKS_PER_REGISTRY)]
    assert len(DomainPackRegistry(packs)) == MAX_PACKS_PER_REGISTRY
    packs.append(DomainPack("example.over", "1"))
    with pytest.raises(DomainPackBoundError):
        DomainPackRegistry(packs)


def test_static_source_has_no_discovery_execution_or_impure_facilities():
    root = Path(__file__).parents[1] / "src" / "scenario_engine" / "domain_packs"
    forbidden_imports = {
        "importlib", "pkgutil", "subprocess", "multiprocessing", "random", "secrets",
        "socket", "urllib", "http", "requests", "os", "time", "datetime",
    }
    forbidden_calls = {"eval", "exec", "__import__", "entry_points"}
    for path in root.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(alias.name.split(".")[0] not in forbidden_imports for alias in node.names)
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in forbidden_imports
            if isinstance(node, ast.Call):
                name = getattr(node.func, "id", getattr(node.func, "attr", ""))
                assert name not in forbidden_calls
                if name == "compile":
                    assert isinstance(node.func, ast.Attribute)
                    assert isinstance(node.func.value, ast.Name)
                    assert node.func.value.id == "re"
        assert "import_module" not in source
        assert "pkg_resources" not in source
        assert "environ" not in source


def test_public_contract_is_complete_and_no_global_registry_exists():
    import scenario_engine.domain_packs as public

    assert public.__all__ == [
        "DOMAIN_PACK_SCHEMA_VERSION", "MAX_ASSETS_PER_PACK", "MAX_CANONICAL_PACK_BYTES",
        "MAX_PACKS_PER_REGISTRY", "DomainPack", "DomainPackBoundError",
        "DomainPackCollisionError", "DomainPackDefinitionError", "DomainPackError",
        "DomainPackNotFoundError", "DomainPackRegistry", "PluginRequirement",
        "canonical_domain_pack_bytes", "domain_pack_content_hash",
    ]
    assert not any("REGISTRY" in name and name != "MAX_PACKS_PER_REGISTRY" for name in vars(public))
