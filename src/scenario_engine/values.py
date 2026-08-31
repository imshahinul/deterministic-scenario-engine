from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from typing import Any, Mapping

from .ids import LogicalID


class _Missing:
    __slots__ = ()

    def __copy__(self) -> _Missing:
        return self

    def __deepcopy__(self, memo: dict[int, Any]) -> _Missing:
        memo[id(self)] = self
        return self

    def __repr__(self) -> str:
        return "MISSING"


MISSING = _Missing()


def normalize(value: Any) -> Any:
    if value is MISSING:
        return {"$type": "missing"}
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, Decimal):
        return {"$type": "decimal", "value": str(value)}
    if isinstance(value, str):
        return value
    if isinstance(value, LogicalID):
        return {"$type": "logical-id", "value": value.value}
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("datetime values must be timezone-aware")
        utc = value.astimezone(timezone.utc)
        return {"$type": "datetime", "value": utc.isoformat(timespec="microseconds")}
    if isinstance(value, timedelta):
        total_micros = ((value.days * 86400 + value.seconds) * 1_000_000 + value.microseconds)
        return {"$type": "duration-microseconds", "value": total_micros}
    if isinstance(value, (list, tuple)):
        return [normalize(item) for item in value]
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("semantic mappings require string keys")
        return {key: normalize(value[key]) for key in sorted(value)}
    raise TypeError(f"unsupported semantic value: {type(value).__name__}")


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(normalize(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()
