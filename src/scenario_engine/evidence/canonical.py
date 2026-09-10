"""Canonical JSON bytes and SHA-256 identity for evidence bundle models."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from enum import Enum
import hashlib
import json
from typing import Any, Mapping

from .errors import EvidenceSerializationError


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {
            item.name: _jsonable(getattr(value, item.name))
            for item in fields(value)
            if item.name != "bundle_id"
        }
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("canonical mappings require string keys")
        return {key: _jsonable(value[key]) for key in sorted(value)}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    raise TypeError(f"unsupported evidence value: {type(value).__name__}")


def _canonical_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            _jsonable(value), ensure_ascii=False, allow_nan=False,
            sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError):
        raise EvidenceSerializationError(
            "evidence model cannot be canonically serialized"
        ) from None


def canonical_evidence_bytes(bundle: Any) -> bytes:
    """Return canonical UTF-8 JSON for an ``EvidenceBundle`` without a newline.

    ``bundle_id`` is deliberately omitted: it is the SHA-256 digest of exactly
    these bytes and therefore is not part of its own hash input.
    """
    from .models import EvidenceBundle

    if not isinstance(bundle, EvidenceBundle):
        raise EvidenceSerializationError("value must be an EvidenceBundle")
    return _canonical_json_bytes(bundle)


def canonical_evidence_text(bundle: Any) -> str:
    """Return the canonical evidence JSON as text."""
    return canonical_evidence_bytes(bundle).decode("utf-8")


def evidence_bundle_hash(bundle: Any) -> str:
    """Return the lowercase SHA-256 identity of canonical bundle bytes."""
    return hashlib.sha256(canonical_evidence_bytes(bundle)).hexdigest()


def _model_identity(value: Any) -> str:
    """Hash a validated identity envelope during model construction."""
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()
