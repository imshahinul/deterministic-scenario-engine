"""Installed, immutable public compatibility fixture delivery."""

from __future__ import annotations

import hashlib
from importlib.resources import files
import json
import os
from pathlib import Path
import shutil
import stat
from typing import Any

from scenario_engine.evidence import EvidenceDestinationError, EvidencePublicationError


RESOURCE_PARTS = ("data", "compatibility", "phase4_11")
RESOURCE_CONTRACT = "scenario.compatibility-fixtures/1"


def _resource_root():
    root = files("scenario_engine")
    for part in RESOURCE_PARTS:
        root = root.joinpath(part)
    return root


def _manifest() -> tuple[bytes, dict[str, Any]]:
    data = _resource_root().joinpath("compatibility-fixtures.json").read_bytes()
    value = json.loads(data)
    if value.get("schema_version") != RESOURCE_CONTRACT:
        raise EvidencePublicationError("packaged compatibility fixture manifest is invalid")
    return data, value


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
