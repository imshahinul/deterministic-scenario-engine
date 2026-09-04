"""Bounded JSON-only interpretation of frozen v1 artifacts."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from .errors import ArtifactBoundError, ArtifactReadError, UnsupportedArtifactVersionError
from .models import ArtifactOrigin, ArtifactReadModel
from .serialization import _decode_semantic, _reject_constant, _unique_object


MAX_ARTIFACT_BYTES = 16 * 1024 * 1024
MAX_ARTIFACT_DEPTH = 64
MAX_ARTIFACT_COLLECTION_ITEMS = 100_000

_MANIFEST_FIELDS = {
    "domain_pack_versions", "dsl_version", "engine_version", "generator_versions",
    "id_algorithm_version", "input_resource_hashes", "locale", "reference_clock_start",
    "rng_algorithm_version", "root_seed", "run_index", "scenario_canonical_hash",
}
_RESULT_FIELDS = {
    "artifacts", "clock", "history", "manifest", "next", "scenario_id", "state", "terminal_transition",
}


def read_v1_manifest_bytes(data: bytes) -> ArtifactReadModel:
    return _read(data, bytes, ArtifactOrigin.V1_MANIFEST)


def read_v1_manifest_text(text: str) -> ArtifactReadModel:
    return _read(text, str, ArtifactOrigin.V1_MANIFEST)


def read_v1_result_bytes(data: bytes) -> ArtifactReadModel:
    return _read(data, bytes, ArtifactOrigin.V1_RESULT)


def read_v1_result_text(text: str) -> ArtifactReadModel:
    return _read(text, str, ArtifactOrigin.V1_RESULT)


def _read(source: bytes | str, expected_type: type[Any], origin: ArtifactOrigin) -> ArtifactReadModel:
    if not isinstance(source, expected_type):
        raise TypeError(f"artifact input must be {expected_type.__name__}")
    if isinstance(source, bytes):
        if len(source) > MAX_ARTIFACT_BYTES:
            raise ArtifactBoundError(f"artifact exceeds {MAX_ARTIFACT_BYTES} bytes")
        try:
            text = source.decode("utf-8")
        except UnicodeDecodeError:
            raise ArtifactReadError("artifact JSON must be UTF-8") from None
    else:
        if len(source.encode("utf-8")) > MAX_ARTIFACT_BYTES:
            raise ArtifactBoundError(f"artifact exceeds {MAX_ARTIFACT_BYTES} bytes")
        text = source
    try:
        raw = json.loads(text, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ArtifactReadError("artifact is not valid strict JSON") from None
    _bound(raw, 0)
    if not isinstance(raw, dict):
        raise ArtifactReadError("artifact root must be an object")
    if origin is ArtifactOrigin.V1_MANIFEST:
        payload = _manifest(raw)
    else:
        payload = _result(raw)
    return ArtifactReadModel(origin=origin, artifact_version="1.0.0", payload=payload)


def _manifest(raw: dict[str, Any]) -> dict[str, Any]:
    _fields(raw, _MANIFEST_FIELDS, "v1 manifest")
    payload = _semantic(raw)
    if payload["engine_version"] != "1.0.0":
        raise UnsupportedArtifactVersionError("v1 manifest engine_version must be 1.0.0")
    if payload["dsl_version"] != 1 or isinstance(payload["dsl_version"], bool):
        raise ArtifactReadError("v1 manifest dsl_version must be integer 1")
    if not isinstance(payload["scenario_canonical_hash"], str) or len(payload["scenario_canonical_hash"]) != 64:
        raise ArtifactReadError("v1 manifest has an invalid scenario hash")
    if any(character not in "0123456789abcdef" for character in payload["scenario_canonical_hash"]):
        raise ArtifactReadError("v1 manifest has an invalid scenario hash")
    if isinstance(payload["root_seed"], bool) or not isinstance(payload["root_seed"], (str, int)):
        raise ArtifactReadError("v1 manifest root_seed has an invalid semantic type")
    if isinstance(payload["run_index"], bool) or not isinstance(payload["run_index"], int) or payload["run_index"] < 0:
        raise ArtifactReadError("v1 manifest run_index has an invalid semantic type")
    for name in ("input_resource_hashes", "domain_pack_versions", "generator_versions"):
        mapping = payload[name]
        if not isinstance(mapping, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in mapping.items()):
            raise ArtifactReadError(f"v1 manifest {name} must map strings to strings")
    for name in ("engine_version", "rng_algorithm_version", "id_algorithm_version", "locale"):
        if not isinstance(payload[name], str) or not payload[name]:
            raise ArtifactReadError(f"v1 manifest {name} must be a non-empty string")
    clock = payload["reference_clock_start"]
    if not isinstance(clock, datetime) or clock.tzinfo is None or clock.utcoffset() is None:
        raise ArtifactReadError("v1 manifest reference_clock_start must be an aware datetime")
    return payload


def _result(raw: dict[str, Any]) -> dict[str, Any]:
    fields = set(raw)
    allowed = _RESULT_FIELDS | {"provenance"}
    if not _RESULT_FIELDS <= fields or not fields <= allowed:
        raise ArtifactReadError("v1 result has missing or unknown structural fields")
    if not isinstance(raw["manifest"], dict):
        raise ArtifactReadError("v1 result manifest must be an object")
    payload = _semantic(raw)
    payload["manifest"] = _manifest(raw["manifest"])
    if not isinstance(payload["scenario_id"], str) or not payload["scenario_id"]:
        raise ArtifactReadError("v1 result scenario_id must be non-empty")
    for name in ("artifacts", "history"):
        if not isinstance(payload[name], tuple):
            raise ArtifactReadError(f"v1 result {name} must be a sequence")
    if not isinstance(payload["state"], dict):
        raise ArtifactReadError("v1 result state must be a mapping")
    return payload


def _semantic(value: Any) -> Any:
    if isinstance(value, list):
        return tuple(_semantic(item) for item in value)
    if isinstance(value, dict):
        if "$type" in value:
            try:
                return _decode_semantic(value)
            except ValueError:
                raise ArtifactReadError("malformed typed semantic value") from None
        return {key: _semantic(item) for key, item in value.items()}
    return value


def _fields(raw: dict[str, Any], expected: set[str], label: str) -> None:
    if set(raw) != expected:
        raise ArtifactReadError(f"{label} has missing or unknown structural fields")


def _bound(value: Any, depth: int) -> None:
    if depth > MAX_ARTIFACT_DEPTH:
        raise ArtifactBoundError(f"artifact nesting exceeds {MAX_ARTIFACT_DEPTH}")
    if isinstance(value, dict):
        if len(value) > MAX_ARTIFACT_COLLECTION_ITEMS:
            raise ArtifactBoundError("artifact mapping exceeds collection bound")
        for item in value.values():
            _bound(item, depth + 1)
    elif isinstance(value, list):
        if len(value) > MAX_ARTIFACT_COLLECTION_ITEMS:
            raise ArtifactBoundError("artifact sequence exceeds collection bound")
        for item in value:
            _bound(item, depth + 1)
