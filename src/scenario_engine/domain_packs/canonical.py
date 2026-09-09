"""Canonical semantic identity for declarative domain packs."""

from __future__ import annotations

import hashlib
from typing import Any

from scenario_engine.values import canonical_bytes

from .errors import DomainPackBoundError, DomainPackDefinitionError
from .models import DomainPack, MAX_CANONICAL_PACK_BYTES


def _payload(pack: DomainPack) -> dict[str, Any]:
    if not isinstance(pack, DomainPack):
        raise DomainPackDefinitionError("value must be a DomainPack")
    return {
        "constraints": pack.constraints,
        "documentation": pack.documentation,
        "name": pack.name,
        "oracle_fragments": pack.oracle_fragments,
        "plugin_requirements": tuple(
            {"name": item.name, "version": item.version}
            for item in pack.plugin_requirements
        ),
        "resource_templates": pack.resource_templates,
        "schema_version": pack.schema_version,
        "validators": pack.validators,
        "version": pack.version,
    }


def canonical_domain_pack_bytes(pack: DomainPack) -> bytes:
    data = canonical_bytes(_payload(pack))
    if len(data) > MAX_CANONICAL_PACK_BYTES:
        raise DomainPackBoundError(
            f"canonical domain pack exceeds {MAX_CANONICAL_PACK_BYTES} bytes"
        )
    return data


def domain_pack_content_hash(pack: DomainPack) -> str:
    return hashlib.sha256(canonical_domain_pack_bytes(pack)).hexdigest()
