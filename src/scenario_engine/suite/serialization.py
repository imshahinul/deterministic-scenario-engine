"""Canonical JSON serialization and strict parsing for suite contracts."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
import json
from typing import Any, Mapping

from scenario_engine.ids import LogicalID
from scenario_engine.manifest import ReproducibilityManifest
from scenario_engine.values import MISSING, normalize

from .errors import SuiteSerializationError
from .models import (
    ArtifactOrigin,
    ArtifactReadModel,
    ArtifactReference,
    BatchItemResult,
    BatchManifest,
    BatchResultEnvelope,
    BatchStatus,
    BoundsMetadata,
    CompatibilityRecord,
    DomainPackRecord,
    ExecutionContext,
    ExecutionReplaySupport,
    FailureRecord,
    MatrixCase,
    MatrixCaseResultEnvelope,
    MatrixManifest,
    MatrixResultEnvelope,
    ReadSupport,
    RunManifestEnvelope,
    SuiteManifest,
)


_MODELS = {
    cls.__name__: cls for cls in (
        ArtifactReadModel,
        ArtifactReference,
        BatchItemResult,
        BatchManifest,
        BatchResultEnvelope,
        BoundsMetadata,
        CompatibilityRecord,
        DomainPackRecord,
        ExecutionContext,
        FailureRecord,
        MatrixCase,
        MatrixCaseResultEnvelope,
        MatrixManifest,
        MatrixResultEnvelope,
        RunManifestEnvelope,
        SuiteManifest,
    )
}
_ENUMS = {
    cls.__name__: cls for cls in (
        ArtifactOrigin,
        BatchStatus,
        ExecutionReplaySupport,
        ReadSupport,
    )
}


def canonical_suite_bytes(value: Any) -> bytes:
    """Return the sole compact UTF-8 JSON representation of a suite model."""
    if type(value).__name__ not in _MODELS:
        raise SuiteSerializationError("value is not a supported suite model")
    try:
        return json.dumps(
            _encode(value), ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise SuiteSerializationError("suite model cannot be canonically serialized") from None


def canonical_suite_text(value: Any) -> str:
    return canonical_suite_bytes(value).decode("utf-8")


def parse_suite_bytes(data: bytes) -> Any:
    if not isinstance(data, bytes):
        raise TypeError("data must be bytes")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise SuiteSerializationError("suite JSON must be UTF-8") from None
    return parse_suite_text(text)


def parse_suite_text(text: str) -> Any:
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    try:
        raw = json.loads(text, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
        value = _decode(raw)
    except SuiteSerializationError:
        raise
    except (TypeError, ValueError, KeyError) as exc:
        raise SuiteSerializationError("invalid suite JSON contract") from None
    if type(value).__name__ not in _MODELS:
        raise SuiteSerializationError("suite JSON root must be a supported model")
    return value


def _encode(value: Any) -> Any:
    if isinstance(value, Enum):
        return {"$enum": type(value).__name__, "value": value.value}
    if value is MISSING or value is None or isinstance(value, (bool, int, str, Decimal, datetime, LogicalID)):
        return normalize(value)
    if isinstance(value, ReproducibilityManifest):
        return {"$model": "ReproducibilityManifest", **value.normalized()}
    if is_dataclass(value):
        result = {"$model": type(value).__name__}
        for item in fields(value):
            field_value = getattr(value, item.name)
            if isinstance(value, MatrixCase) and item.name == "assignment":
                result[item.name] = [[key, _encode(field_value[key])] for key in field_value]
            else:
                result[item.name] = _encode(field_value)
        return result
    if isinstance(value, Mapping):
        return {key: _encode(value[key]) for key in value}
    if isinstance(value, (tuple, list)):
        return [_encode(item) for item in value]
    raise TypeError(f"unsupported suite value: {type(value).__name__}")


def _decode(value: Any) -> Any:
    if isinstance(value, list):
        return tuple(_decode(item) for item in value)
    if not isinstance(value, dict):
        return value
    if "$type" in value:
        return _decode_semantic(value)
    if "$enum" in value:
        if set(value) != {"$enum", "value"} or value["$enum"] not in _ENUMS:
            raise SuiteSerializationError("invalid suite enum")
        return _ENUMS[value["$enum"]](value["value"])
    model_name = value.get("$model")
    if model_name is None:
        return {key: _decode(item) for key, item in value.items()}
    if model_name == "ReproducibilityManifest":
        expected = {
            "$model", "domain_pack_versions", "dsl_version", "engine_version", "generator_versions",
            "id_algorithm_version", "input_resource_hashes", "locale", "reference_clock_start",
            "rng_algorithm_version", "root_seed", "run_index", "scenario_canonical_hash",
        }
        _exact(value, expected)
        kwargs = {key: _decode(item) for key, item in value.items() if key != "$model"}
        return ReproducibilityManifest(**kwargs)
    cls = _MODELS.get(model_name)
    if cls is None:
        raise SuiteSerializationError(f"unknown suite model: {model_name}")
    expected = {"$model", *(item.name for item in fields(cls))}
    _exact(value, expected)
    kwargs = {key: _decode(item) for key, item in value.items() if key != "$model"}
    if cls is MatrixCase:
        assignment = kwargs["assignment"]
        if not isinstance(assignment, tuple):
            raise SuiteSerializationError("matrix assignment must be an ordered pair sequence")
        ordered: dict[str, Any] = {}
        for pair in assignment:
            if not isinstance(pair, tuple) or len(pair) != 2 or not isinstance(pair[0], str) or pair[0] in ordered:
                raise SuiteSerializationError("invalid or duplicate matrix assignment name")
            ordered[pair[0]] = pair[1]
        kwargs["assignment"] = ordered
    return cls(**kwargs)


def _decode_semantic(value: dict[str, Any]) -> Any:
    kind = value.get("$type")
    if kind == "missing" and set(value) == {"$type"}:
        return MISSING
    if set(value) != {"$type", "value"}:
        raise SuiteSerializationError("malformed typed semantic value")
    raw = value["value"]
    try:
        if kind == "decimal" and isinstance(raw, str):
            parsed = Decimal(raw)
            if not parsed.is_finite():
                raise ValueError
            return parsed
        if kind == "logical-id" and isinstance(raw, str):
            return LogicalID(raw)
        if kind == "datetime" and isinstance(raw, str):
            parsed = datetime.fromisoformat(raw)
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                raise ValueError
            return parsed
        if kind == "duration-microseconds" and isinstance(raw, int) and not isinstance(raw, bool):
            from datetime import timedelta
            return timedelta(microseconds=raw)
    except (ValueError, ArithmeticError):
        pass
    raise SuiteSerializationError("malformed typed semantic value")


def _exact(value: dict[str, Any], expected: set[str]) -> None:
    if set(value) != expected:
        missing = sorted(expected - set(value))
        unknown = sorted(set(value) - expected)
        detail = "missing " + ",".join(missing) if missing else "unknown " + ",".join(unknown)
        raise SuiteSerializationError(f"strict suite schema fields: {detail}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SuiteSerializationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> Any:
    raise SuiteSerializationError(f"non-finite JSON number is forbidden: {value}")
