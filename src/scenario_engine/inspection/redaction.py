"""Explicit, environment-independent inspection redaction."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from .errors import RedactionConfigurationError


DEFAULT_SECRET_KEYS = frozenset({
    "access_key", "api_key", "authorization", "passwd", "password",
    "private_key", "secret", "token",
})


def validate_redacted_keys(keys: Iterable[str] | None) -> frozenset[str]:
    if keys is None:
        return DEFAULT_SECRET_KEYS
    if isinstance(keys, (str, bytes)):
        raise RedactionConfigurationError("redacted_keys must be an iterable of key names")
    try:
        result = frozenset(keys)
    except TypeError:
        raise RedactionConfigurationError("redacted_keys must be an iterable of key names") from None
    if not all(isinstance(key, str) and key for key in result):
        raise RedactionConfigurationError("redacted_keys must contain nonempty strings")
    return frozenset(key.casefold() for key in result) | DEFAULT_SECRET_KEYS


def redact_mapping(value: Mapping[str, Any], keys: frozenset[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in sorted(value):
        item = value[key]
        if key.casefold() in keys:
            result[key] = {"availability": "redacted", "reason": "configured_secret_key"}
        elif isinstance(item, Mapping):
            result[key] = redact_mapping(item, keys)
        elif isinstance(item, (list, tuple)):
            result[key] = [_redact_item(child, keys) for child in item]
        else:
            result[key] = item
    return result


def _redact_item(value: Any, keys: frozenset[str]) -> Any:
    if isinstance(value, Mapping):
        return redact_mapping(value, keys)
    if isinstance(value, (list, tuple)):
        return [_redact_item(item, keys) for item in value]
    return value
