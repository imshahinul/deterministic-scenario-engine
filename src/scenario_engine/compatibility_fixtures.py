"""Installed, immutable public compatibility fixture delivery."""

from __future__ import annotations

import hashlib
from importlib.resources import files
import json
import os
from pathlib import Path
import shutil
import stat
from types import MappingProxyType
from typing import Any, Mapping

from scenario_engine.evidence import EvidenceDestinationError, EvidencePublicationError


RESOURCE_PARTS = ("data", "compatibility", "phase4_11")
RESOURCE_CONTRACT = "scenario.compatibility-fixtures/1"
ENGINE2_RESOURCE_PARTS = ("data", "compatibility", "phase5_10")
ENGINE2_RESOURCE_CONTRACT = "scenario.compatibility-fixtures/2"
ENGINE2_FIXTURE_SET = "phase5_10"
MAX_FIXTURE_MANIFEST_BYTES = 1_048_576
MAX_FIXTURE_RESOURCE_BYTES = 33_554_432
_SHA256 = __import__("re").compile(r"[0-9a-f]{64}\Z")


def _resource_root(parts: tuple[str, ...] = RESOURCE_PARTS):
    root = files("scenario_engine")
    for part in parts:
        root = root.joinpath(part)
    return root


def _manifest() -> tuple[bytes, dict[str, Any]]:
    data = _resource_root().joinpath("compatibility-fixtures.json").read_bytes()
    value = json.loads(data)
    if value.get("schema_version") != RESOURCE_CONTRACT:
        raise EvidencePublicationError("packaged compatibility fixture manifest is invalid")
    return data, value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EvidencePublicationError("packaged compatibility fixture manifest is invalid")
        result[key] = value
    return result


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def _safe_relative_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise EvidencePublicationError("packaged compatibility fixture manifest is invalid")
    path = Path(value)
    if path.is_absolute() or value != path.as_posix() or any(part in ("", ".", "..") for part in path.parts):
        raise EvidencePublicationError("packaged compatibility fixture manifest is invalid")
    return value


def _digest(value: object) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise EvidencePublicationError("packaged compatibility fixture manifest is invalid")
    return value


def read_engine2_fixture_manifest() -> Mapping[str, Any]:
    """Strictly read the immutable installed Phase 5.10 fixture index."""
    resource = _resource_root(ENGINE2_RESOURCE_PARTS).joinpath("compatibility-fixtures.json")
    data = resource.read_bytes()
    if len(data) > MAX_FIXTURE_MANIFEST_BYTES:
        raise EvidencePublicationError("packaged compatibility fixture manifest is invalid")
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_object,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except EvidencePublicationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError):
        raise EvidencePublicationError("packaged compatibility fixture manifest is invalid") from None
    top = {"schema_version", "fixture_set", "operation_order", "fixtures", "support_files"}
    if not isinstance(value, dict) or set(value) != top or _canonical(value) != data:
        raise EvidencePublicationError("packaged compatibility fixture manifest is invalid")
    if value["schema_version"] != ENGINE2_RESOURCE_CONTRACT or value["fixture_set"] != ENGINE2_FIXTURE_SET:
        raise EvidencePublicationError("packaged compatibility fixture manifest is invalid")
    if value["operation_order"] != ["execute", "replay", "inspect", "read"]:
        raise EvidencePublicationError("packaged compatibility fixture manifest is invalid")
    if not isinstance(value["fixtures"], list) or not isinstance(value["support_files"], list):
        raise EvidencePublicationError("packaged compatibility fixture manifest is invalid")
    fixture_fields = {"id", "artifact_contract", "engine_version", "dsl_version", "operation",
                      "expected_classification", "path", "sha256", "provenance"}
    provenance_fields = {"kind", "source", "coordinates"}
    ids: list[str] = []
    for item in value["fixtures"]:
        if not isinstance(item, dict) or set(item) != fixture_fields:
            raise EvidencePublicationError("packaged compatibility fixture manifest is invalid")
        if not all(isinstance(item[name], str) and item[name] for name in
                   ("id", "artifact_contract", "engine_version", "operation", "expected_classification")):
            raise EvidencePublicationError("packaged compatibility fixture manifest is invalid")
        if isinstance(item["dsl_version"], bool) or not isinstance(item["dsl_version"], int):
            raise EvidencePublicationError("packaged compatibility fixture manifest is invalid")
        provenance = item["provenance"]
        if (not isinstance(provenance, dict) or set(provenance) != provenance_fields or
                not isinstance(provenance["kind"], str) or not isinstance(provenance["source"], str) or
                not isinstance(provenance["coordinates"], dict)):
            raise EvidencePublicationError("packaged compatibility fixture manifest is invalid")
        ids.append(item["id"]); _safe_relative_path(item["path"]); _digest(item["sha256"])
    if ids != sorted(ids, key=str.encode) or len(ids) != len(set(ids)) or len(ids) != 30:
        raise EvidencePublicationError("packaged compatibility fixture manifest is invalid")
    support_fields = {"path", "sha256", "role"}
    support_paths: list[str] = []
    for item in value["support_files"]:
        if (not isinstance(item, dict) or set(item) != support_fields or
                not isinstance(item["role"], str) or not item["role"]):
            raise EvidencePublicationError("packaged compatibility fixture manifest is invalid")
        support_paths.append(_safe_relative_path(item["path"])); _digest(item["sha256"])
    if support_paths != sorted(support_paths, key=str.encode) or len(support_paths) != len(set(support_paths)):
        raise EvidencePublicationError("packaged compatibility fixture manifest is invalid")
    return MappingProxyType(value)


def verify_engine2_compatibility_fixtures() -> tuple[str, ...]:
    """Verify every declared Phase 5.10 resource and return deterministic paths."""
    manifest = read_engine2_fixture_manifest()
    root = _resource_root(ENGINE2_RESOURCE_PARTS)
    declared: dict[str, str] = {}
    for item in (*manifest["fixtures"], *manifest["support_files"]):
        path, digest = item["path"], item["sha256"]
        if path in declared and declared[path] != digest:
            raise EvidencePublicationError("packaged compatibility fixture manifest is invalid")
        declared[path] = digest
    for relative, expected in sorted(declared.items(), key=lambda item: item[0].encode("utf-8")):
        resource = root.joinpath(*relative.split("/"))
        data = resource.read_bytes()
        limit = 8_388_608 if relative.endswith("schedule-v1.json") else MAX_FIXTURE_RESOURCE_BYTES
        if len(data) > limit or hashlib.sha256(data).hexdigest() != expected:
            raise EvidencePublicationError("packaged compatibility fixture failed its frozen SHA-256")
    return tuple(sorted(declared, key=str.encode))


def _declared_files(manifest: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    declared: dict[str, str] = {}
    for item in (*manifest["fixtures"], *manifest["support_files"]):
        path, digest = item["path"], item["sha256"]
        if path in declared or Path(path).is_absolute() or ".." in Path(path).parts:
            raise EvidencePublicationError("packaged compatibility fixture manifest is invalid")
        declared[path] = digest
    return tuple(sorted(declared.items()))


def _safe_absent_destination(destination: Path) -> Path:
    if not destination.is_absolute() or destination.name in ("", ".", ".."):
        raise EvidenceDestinationError(
            "compatibility fixture destination must be an explicit absolute path"
        )
    if os.path.lexists(destination):
        raise EvidenceDestinationError("compatibility fixture destination already exists")
    parent = destination.parent
    try:
        current = parent
        while True:
            metadata = current.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                raise EvidenceDestinationError("destination parent contains a symlink")
            if current == current.parent:
                break
            current = current.parent
    except FileNotFoundError:
        raise EvidenceDestinationError("destination parent does not exist") from None
    except OSError:
        raise EvidenceDestinationError("destination parent cannot be inspected") from None
    if not parent.is_dir():
        raise EvidenceDestinationError("destination parent must be a directory")
    return destination


def export_compatibility_fixtures(destination: str | os.PathLike[str]) -> Path:
    """Copy verified frozen package resources to one absent absolute directory."""
    target = _safe_absent_destination(Path(destination))
    manifest_bytes, manifest = _manifest()
    root = _resource_root()
    declared = _declared_files(manifest)
    try:
        target.mkdir(mode=0o755)
        (target / "compatibility-fixtures.json").write_bytes(manifest_bytes)
        for relative, expected in declared:
            source = root.joinpath(*relative.split("/"))
            data = source.read_bytes()
            if hashlib.sha256(data).hexdigest() != expected:
                raise EvidencePublicationError(
                    "packaged compatibility fixture failed its frozen SHA-256"
                )
            output = target.joinpath(*relative.split("/"))
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(data)
    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        raise
    return target


def export_engine2_compatibility_fixtures(destination: str | os.PathLike[str]) -> Path:
    """Copy the verified immutable Phase 5.10 pack to one absent absolute directory."""
    target = _safe_absent_destination(Path(destination))
    manifest = read_engine2_fixture_manifest()
    paths = verify_engine2_compatibility_fixtures()
    root = _resource_root(ENGINE2_RESOURCE_PARTS)
    manifest_bytes = root.joinpath("compatibility-fixtures.json").read_bytes()
    try:
        target.mkdir(mode=0o755)
        (target / "compatibility-fixtures.json").write_bytes(manifest_bytes)
        for relative in paths:
            output = target.joinpath(*relative.split("/"))
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(root.joinpath(*relative.split("/")).read_bytes())
    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        raise
    return target
