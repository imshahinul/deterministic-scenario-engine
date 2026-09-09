"""Explicit immutable declarative Domain Pack foundation."""

from .canonical import canonical_domain_pack_bytes, domain_pack_content_hash
from .errors import (
    DomainPackBoundError,
    DomainPackCollisionError,
    DomainPackDefinitionError,
    DomainPackError,
    DomainPackNotFoundError,
)
from .models import (
    DOMAIN_PACK_SCHEMA_VERSION,
    MAX_ASSETS_PER_PACK,
    MAX_CANONICAL_PACK_BYTES,
    DomainPack,
    PluginRequirement,
)
from .registry import MAX_PACKS_PER_REGISTRY, DomainPackRegistry


__all__ = [
    "DOMAIN_PACK_SCHEMA_VERSION",
    "MAX_ASSETS_PER_PACK",
    "MAX_CANONICAL_PACK_BYTES",
    "MAX_PACKS_PER_REGISTRY",
    "DomainPack",
    "DomainPackBoundError",
    "DomainPackCollisionError",
    "DomainPackDefinitionError",
    "DomainPackError",
    "DomainPackNotFoundError",
    "DomainPackRegistry",
    "PluginRequirement",
    "canonical_domain_pack_bytes",
    "domain_pack_content_hash",
]
