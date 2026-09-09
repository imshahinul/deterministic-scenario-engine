"""Explicit immutable domain-pack registry and exact deterministic resolution."""

from __future__ import annotations

from types import MappingProxyType
from typing import Iterable, Iterator, Mapping

from scenario_engine.plugins import PluginRegistry

from .errors import (
    DomainPackBoundError,
    DomainPackCollisionError,
    DomainPackDefinitionError,
    DomainPackNotFoundError,
)
from .models import DomainPack, PluginRequirement, validate_pack_name, validate_pack_version


MAX_PACKS_PER_REGISTRY = 1_000


class DomainPackRegistry:
    """Caller-created immutable registry; iterable input order has no semantics."""

    __slots__ = ("_packs",)

    def __init__(self, packs: Iterable[DomainPack] = ()) -> None:
        collected: dict[tuple[str, str], DomainPack] = {}
        names: set[str] = set()
        for pack in packs:
            if not isinstance(pack, DomainPack):
                raise DomainPackDefinitionError("registry entries must be DomainPack objects")
            coordinate = (pack.name, pack.version)
            if coordinate in collected:
                raise DomainPackCollisionError(f"duplicate domain pack coordinate: {pack.coordinate}")
            if pack.name in names:
                raise DomainPackCollisionError(
                    f"conflicting domain pack versions for identity: {pack.name}"
                )
            if len(collected) == MAX_PACKS_PER_REGISTRY:
                raise DomainPackBoundError(
                    f"domain pack registry exceeds {MAX_PACKS_PER_REGISTRY} packs"
                )
            collected[coordinate] = pack
            names.add(pack.name)
        self._packs: Mapping[tuple[str, str], DomainPack] = MappingProxyType(
            {coordinate: collected[coordinate] for coordinate in sorted(collected)}
        )

    def resolve(self, name: str, version: str) -> DomainPack:
        coordinate = (validate_pack_name(name), validate_pack_version(version))
        try:
            return self._packs[coordinate]
        except KeyError:
            raise DomainPackNotFoundError(
                f"domain pack not found: {coordinate[0]}@{coordinate[1]}"
            ) from None

    def resolve_all(
        self, requirements: Iterable[tuple[str, str]]
    ) -> tuple[DomainPack, ...]:
        coordinates = tuple(requirements)
        if len(coordinates) > MAX_PACKS_PER_REGISTRY:
            raise DomainPackBoundError(
                f"domain pack requirements exceed {MAX_PACKS_PER_REGISTRY}"
            )
        validated: list[tuple[str, str]] = []
        for coordinate in coordinates:
            if not isinstance(coordinate, tuple) or len(coordinate) != 2:
                raise DomainPackDefinitionError(
                    "domain pack requirements must be exact (name, version) tuples"
                )
            validated.append(
                (validate_pack_name(coordinate[0]), validate_pack_version(coordinate[1]))
            )
        if len(set(validated)) != len(validated):
            raise DomainPackCollisionError("domain pack requirements contain a duplicate coordinate")
        names = [name for name, _ in validated]
        if len(set(names)) != len(names):
            raise DomainPackCollisionError("domain pack requirements contain conflicting versions")
        return tuple(self.resolve(*coordinate) for coordinate in sorted(validated))

    def validate_plugins(self, pack: DomainPack, registry: PluginRegistry) -> None:
        """Validate declarative requirements only through a caller-supplied registry."""
        if not isinstance(registry, PluginRegistry):
            raise DomainPackDefinitionError("registry must be an explicit PluginRegistry")
        for requirement in pack.plugin_requirements:
            registry.require(requirement.name, requirement.version)

    def __iter__(self) -> Iterator[DomainPack]:
        return iter(self._packs.values())

    def __len__(self) -> int:
        return len(self._packs)
