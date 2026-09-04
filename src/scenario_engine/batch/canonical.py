"""Canonical identities for immutable deterministic batch plans."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import hashlib
import json
from typing import Any, Mapping

from scenario_engine.ids import LogicalID
from scenario_engine.values import MISSING, normalize


BATCH_PLAN_IDENTITY_VERSION = "batch.plan/1"


def _jsonable(value: Any) -> Any:
    if value is MISSING or value is None or isinstance(
        value, (bool, int, str, Decimal, datetime, LogicalID)
    ):
        return normalize(value)
    if isinstance(value, Mapping):
        return {key: _jsonable(value[key]) for key in sorted(value)}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    raise TypeError(f"unsupported batch semantic value: {type(value).__name__}")


def canonical_batch_bytes(value: Mapping[str, Any]) -> bytes:
    """Encode a batch identity payload as compact canonical UTF-8 JSON."""
    return json.dumps(
        _jsonable(value), ensure_ascii=False, allow_nan=False,
        sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def canonical_hash(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_batch_bytes(value)).hexdigest()
