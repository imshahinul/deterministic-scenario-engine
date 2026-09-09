"""Immutable declarative domain-pack models."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from types import MappingProxyType
from typing import Any, Mapping

from scenario_engine.values import normalize

from .errors import DomainPackBoundError, DomainPackDefinitionError


DOMAIN_PACK_SCHEMA_VERSION = "domain-pack/1"
MAX_ASSETS_PER_PACK = 10_000
MAX_CANONICAL_PACK_BYTES = 16 * 1024 * 1024
_PACK_NAME = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
_ASSET_KINDS = (
    "constraints",
    "documentation",
    "oracle_fragments",
    "resource_templates",
    "validators",
)


def validate_pack_name(value: Any) -> str:
    if not isinstance(value, str) or _PACK_NAME.fullmatch(value) is None:
        raise DomainPackDefinitionError(
            "domain pack name must be lowercase namespaced ASCII components"
        )
    return value


def validate_pack_version(value: Any) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise DomainPackDefinitionError(
            "domain pack version must be an exact non-empty string without surrounding whitespace"
        )
    if any(ord(character) < 0x21 or ord(character) > 0x7E for character in value):
        raise DomainPackDefinitionError("domain pack version must use visible ASCII characters")
    return value


def _freeze_semantic(value: Any) -> Any:
    try:
        normalize(value)
    except (TypeError, ValueError):
        raise DomainPackDefinitionError("domain pack assets contain an invalid semantic value") from None
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_semantic(value[key]) for key in sorted(value)})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_semantic(item) for item in value)
    return value


def _freeze_assets(value: Any, kind: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) and key for key in value):
        raise DomainPackDefinitionError(f"{kind} must be a mapping with non-empty string keys")
    if len(value) > MAX_ASSETS_PER_PACK:
        raise DomainPackBoundError(f"{kind} exceeds {MAX_ASSETS_PER_PACK} assets")
    return MappingProxyType({key: _freeze_semantic(value[key]) for key in sorted(value)})


@dataclass(frozen=True, slots=True)
class PluginRequirement:
    """A declarative exact plugin capability reference; it never loads or invokes code."""

    name: str
    version: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", validate_pack_name(self.name))
        object.__setattr__(self, "version", validate_pack_version(self.version))


@dataclass(frozen=True, slots=True)
class DomainPack:
    """An immutable, versioned bundle of namespaced declarative assets."""

    name: str
    version: str
    resource_templates: Mapping[str, Any] = field(default_factory=dict)
    validators: Mapping[str, Any] = field(default_factory=dict)
    constraints: Mapping[str, Any] = field(default_factory=dict)
    oracle_fragments: Mapping[str, Any] = field(default_factory=dict)
    documentation: Mapping[str, Any] = field(default_factory=dict)
    plugin_requirements: tuple[PluginRequirement, ...] = ()
    schema_version: str = DOMAIN_PACK_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", validate_pack_name(self.name))
        object.__setattr__(self, "version", validate_pack_version(self.version))
        if self.schema_version != DOMAIN_PACK_SCHEMA_VERSION:
            raise DomainPackDefinitionError(
                f"unsupported domain pack schema version: {self.schema_version}"
            )
        total = 0
        for kind in _ASSET_KINDS:
            frozen = _freeze_assets(getattr(self, kind), kind)
            total += len(frozen)
            object.__setattr__(self, kind, frozen)
        if total > MAX_ASSETS_PER_PACK:
            raise DomainPackBoundError(
                f"domain pack declarative assets exceed {MAX_ASSETS_PER_PACK}"
            )
        requirements = tuple(self.plugin_requirements)
        if not all(isinstance(item, PluginRequirement) for item in requirements):
            raise DomainPackDefinitionError(
                "plugin_requirements must contain PluginRequirement values"
            )
        if len(requirements) > MAX_ASSETS_PER_PACK:
            raise DomainPackBoundError(
                f"plugin_requirements exceeds {MAX_ASSETS_PER_PACK}"
            )
        coordinates = [(item.name, item.version) for item in requirements]
        if len(set(coordinates)) != len(coordinates):
            raise DomainPackDefinitionError("plugin_requirements contains a duplicate coordinate")
        object.__setattr__(
            self,
            "plugin_requirements",
            tuple(sorted(requirements, key=lambda item: (item.name, item.version))),
        )

    @property
    def coordinate(self) -> str:
        return f"{self.name}@{self.version}"

    def canonical_bytes(self) -> bytes:
        from .canonical import canonical_domain_pack_bytes

        return canonical_domain_pack_bytes(self)

    @property
    def content_hash(self) -> str:
        from .canonical import domain_pack_content_hash

        return domain_pack_content_hash(self)

    def to_record(self):
        from scenario_engine.suite import DomainPackRecord

        return DomainPackRecord(
            identity=self.name,
            version=self.version,
            content_hash=self.content_hash,
        )

    def composition_assets(self) -> Mapping[str, Mapping[str, Any]]:
        """Expose declarations without resolving or duplicating composition behavior."""
        return MappingProxyType({kind: getattr(self, kind) for kind in _ASSET_KINDS})
