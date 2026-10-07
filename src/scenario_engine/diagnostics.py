"""Bounded canonical diagnostics with deterministic human and JSON renderers."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
import unicodedata
from typing import Mapping
from urllib.parse import quote


MAX_DIAGNOSTIC_FIELD_CHARS = 512
MAX_DIAGNOSTIC_DETAIL_KEY_CHARS = 128
MAX_DIAGNOSTIC_DETAILS = 1_000
MAX_SEMANTIC_ADDRESS_BYTES = 2048
MAX_SEMANTIC_ADDRESS_DEPTH = 32
ERROR_ENVELOPE_SCHEMA = "scenario.error/1"
_SPACE = re.compile(r"\s+")
_EXTENSION_KIND = re.compile(r"x-[a-z0-9-]+\Z")
_STANDARD_KINDS = frozenset({
    "constraint", "derive", "emit", "fault", "generator", "invariant", "oracle",
    "resource", "state", "step", "transition", "write",
})
_RESERVED_KINDS = frozenset({"actor", "lane"})
_SECRET_KEY_PARTS = frozenset({
    "access_key", "api_key", "authorization", "passwd", "password", "private_key",
    "secret", "token",
})


def bounded_text(value: object, *, limit: int = MAX_DIAGNOSTIC_FIELD_CHARS) -> str:
    """Return one deterministic bounded line without invoking object repr."""
    text = value if isinstance(value, str) else type(value).__name__
    return _SPACE.sub(" ", text.replace("\x00", "")).strip()[:limit]


def semantic_address(*components: tuple[str, str]) -> str | None:
    """Produce a bounded canonical scenario.semantic-address/1 address."""
    if not components or len(components) > MAX_SEMANTIC_ADDRESS_DEPTH:
        return None
    encoded: list[str] = []
    for component in components:
        if not isinstance(component, tuple) or len(component) != 2:
            return None
        kind, identifier = component
        if (not isinstance(kind, str) or not isinstance(identifier, str)
                or kind in _RESERVED_KINDS
                or (kind not in _STANDARD_KINDS and _EXTENSION_KIND.fullmatch(kind) is None)
                or not identifier or identifier in {".", ".."}):
            return None
        try:
            normalized = unicodedata.normalize("NFC", identifier)
            token = quote(normalized, safe="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
        except (TypeError, UnicodeError):
            return None
        encoded.extend((kind, token))
    result = "scenario:/" + "/".join(encoded)
    return result if len(result.encode("utf-8")) <= MAX_SEMANTIC_ADDRESS_BYTES else None


@dataclass(frozen=True, slots=True)
class HumanDiagnostic:
    """Canonical internal diagnostic shared by human and machine renderers."""

    code: str
    category: str
    message: str
    semantic_path: str | None = None
    expected: str | None = None
    received: str | None = None
    remediation: str | None = None
    details: Mapping[str, str | int | bool] | None = None


def render_human_diagnostic(diagnostic: HumanDiagnostic) -> str:
    """Render stable fields in deterministic human-readable order."""
    lines = [f"scenario: error: {bounded_text(diagnostic.code)}", f"category: {bounded_text(diagnostic.category)}"]
    if diagnostic.semantic_path is not None:
        lines.extend(("path:", bounded_text(diagnostic.semantic_path, limit=MAX_SEMANTIC_ADDRESS_BYTES)))
    lines.extend(("message:", bounded_text(diagnostic.message)))
    if diagnostic.expected is not None:
        lines.extend(("expected:", bounded_text(diagnostic.expected)))
    if diagnostic.received is not None:
        lines.extend(("received:", bounded_text(diagnostic.received)))
    if diagnostic.remediation is not None:
        lines.extend(("next action:", bounded_text(diagnostic.remediation)))
    return "\n".join(lines) + "\n"


def error_envelope(diagnostic: HumanDiagnostic, exit_code: int) -> dict[str, object]:
    """Build the small public envelope without reinterpreting the diagnostic."""
    value: dict[str, object] = {
        "schema": ERROR_ENVELOPE_SCHEMA,
        "code": bounded_text(diagnostic.code),
        "category": bounded_text(diagnostic.category),
        "exit_code": int(exit_code),
        "message": bounded_text(diagnostic.message),
    }
    if diagnostic.semantic_path is not None:
        value["semantic_path"] = bounded_text(
            diagnostic.semantic_path, limit=MAX_SEMANTIC_ADDRESS_BYTES,
        )
    if diagnostic.expected is not None:
        value["expected"] = bounded_text(diagnostic.expected)
    if diagnostic.received is not None:
        value["received"] = bounded_text(diagnostic.received)
    if diagnostic.remediation is not None:
        value["remediation"] = bounded_text(diagnostic.remediation)
    if diagnostic.details:
        details: dict[str, str | int | bool] = {}
        ordered = sorted(diagnostic.details.items(), key=lambda pair: bounded_text(pair[0]))
        for key, item in ordered[:MAX_DIAGNOSTIC_DETAILS]:
            safe_key = bounded_text(key, limit=MAX_DIAGNOSTIC_DETAIL_KEY_CHARS)
            folded = safe_key.casefold()
            secret = any(part == folded or part in re.split(r"[^a-z0-9]+", folded)
                         for part in _SECRET_KEY_PARTS)
            details[safe_key] = "[REDACTED]" if secret else (
                item if isinstance(item, (bool, int)) else bounded_text(item)
            )
        value["details"] = details
    return value


def render_error_envelope(diagnostic: HumanDiagnostic, exit_code: int) -> str:
    """Serialize scenario.error/1 as canonical compact UTF-8 JSON plus LF."""
    return json.dumps(
        error_envelope(diagnostic, exit_code), ensure_ascii=False, allow_nan=False,
        sort_keys=True, separators=(",", ":"),
    ) + "\n"
