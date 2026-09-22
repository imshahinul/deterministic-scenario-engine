"""Deterministic, atomic export of explicit stable-ID fixture declarations."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any, Sequence

from scenario_engine.values import canonical_bytes

from .errors import EvidenceContractError, EvidenceDestinationError, EvidenceExportBoundError, EvidencePublicationError
from .export import _destination, _export_limit, _write_new_regular
from .models import MAX_ARTIFACT_BYTES, MAX_BUNDLE_ENTRIES, MAX_BUNDLE_INDEX_BYTES, DEFAULT_AGGREGATE_BUNDLE_BYTES


FIXTURE_INDEX_SCHEMA_VERSION = "evidence.fixture-index/1"
FIXTURE_INDEX_FILENAME = "fixtures.json"
MAX_FIXTURES = MAX_BUNDLE_ENTRIES
_FIXTURE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


@dataclass(frozen=True, slots=True)
class FixtureDeclaration:
    fixture_id: str
    payload: Any = field(repr=False, compare=False)
    canonical_payload: bytes = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.fixture_id, str) or _FIXTURE_ID.fullmatch(self.fixture_id) is None:
            raise EvidenceContractError("fixture_id must be a portable safe ASCII identifier")
        try:
            encoded = canonical_bytes(self.payload)
        except (TypeError, ValueError):
            raise EvidenceContractError("fixture payload contains an unsupported semantic value") from None
        if len(encoded) > MAX_ARTIFACT_BYTES:
            raise EvidenceExportBoundError("fixture exceeds the individual artifact byte ceiling")
        object.__setattr__(self, "canonical_payload", encoded)


@dataclass(frozen=True, slots=True)
class FixtureIndexEntry:
    fixture_id: str
    path: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class FixtureIndex:
    entries: tuple[FixtureIndexEntry, ...]
    schema_version: str = FIXTURE_INDEX_SCHEMA_VERSION
    index_id: str = field(init=False)

    def __post_init__(self) -> None:
        entries = tuple(self.entries)
        if self.schema_version != FIXTURE_INDEX_SCHEMA_VERSION:
            raise EvidenceContractError("unsupported fixture index schema version")
        if len(entries) > MAX_FIXTURES:
            raise EvidenceExportBoundError("fixture count exceeds the bounded record ceiling")
        if tuple(sorted(entries, key=lambda item: item.fixture_id)) != entries:
            raise EvidenceContractError("fixture index entries must use fixture ID order")
        object.__setattr__(self, "entries", entries)
        object.__setattr__(self, "index_id", hashlib.sha256(_index_bytes(self, False)).hexdigest())


def canonical_fixture_index_bytes(index: FixtureIndex) -> bytes:
    if not isinstance(index, FixtureIndex):
        raise EvidenceContractError("index must be a FixtureIndex")
    return _index_bytes(index, True)


def export_fixture_directory(
    fixtures: Sequence[FixtureDeclaration],
    *,
    destination: str | os.PathLike[str],
    max_aggregate_bytes: int = DEFAULT_AGGREGATE_BUNDLE_BYTES,
) -> FixtureIndex:
    """Atomically publish caller-declared fixtures ordered by explicit stable ID."""
    limit = _export_limit(max_aggregate_bytes)
    if not isinstance(fixtures, Sequence) or isinstance(fixtures, (str, bytes, bytearray)):
        raise TypeError("fixtures must be an explicit finite sequence")
    declarations = tuple(fixtures)
    if len(declarations) > MAX_FIXTURES:
        raise EvidenceExportBoundError("fixture count exceeds the bounded record ceiling")
    if not all(isinstance(item, FixtureDeclaration) for item in declarations):
        raise EvidenceContractError("fixtures must contain FixtureDeclaration values")
    ids = [item.fixture_id for item in declarations]
    if len(ids) != len(set(ids)):
        raise EvidenceContractError("fixtures contains a duplicate fixture_id")
    if len(ids) != len({item.casefold() for item in ids}):
        raise EvidenceContractError("fixtures contains a case-fold fixture ID collision")
    ordered = tuple(sorted(declarations, key=lambda item: item.fixture_id))
    total = sum(len(item.canonical_payload) for item in ordered)
    if total > limit:
        raise EvidenceExportBoundError("aggregate fixture bytes exceed the export limit")
    entries = tuple(FixtureIndexEntry(
        item.fixture_id, f"fixtures/{item.fixture_id}.json",
        hashlib.sha256(item.canonical_payload).hexdigest(), len(item.canonical_payload),
    ) for item in ordered)
    index = FixtureIndex(entries)
    index_bytes = canonical_fixture_index_bytes(index)
    if len(index_bytes) > MAX_BUNDLE_INDEX_BYTES:
        raise EvidenceExportBoundError("fixture index exceeds the index byte ceiling")
    if total + len(index_bytes) > limit:
        raise EvidenceExportBoundError("aggregate fixture bytes exceed the export limit")
    target, parent = _destination(destination)
    staging: Path | None = Path(tempfile.mkdtemp(prefix=f".{target.name}.stage-", dir=parent))
    try:
        fixture_root = staging / "fixtures"
        fixture_root.mkdir()
        for declaration, entry in zip(ordered, entries):
            _write_new_regular(staging / entry.path, declaration.canonical_payload)
        _write_new_regular(staging / FIXTURE_INDEX_FILENAME, index_bytes)
        _validate_staged(staging, index)
        try:
            os.rename(staging, target)
        except FileExistsError:
            raise EvidenceDestinationError("evidence destination already exists") from None
        except OSError:
            raise EvidencePublicationError("atomic fixture directory publication failed") from None
        staging = None
        return index
    finally:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)


def _index_bytes(index: FixtureIndex, include_identity: bool) -> bytes:
    data: dict[str, Any] = {
        "entries": [{"fixture_id": item.fixture_id, "path": item.path,
                     "sha256": item.sha256, "size_bytes": item.size_bytes} for item in index.entries],
        "schema_version": index.schema_version,
    }
    if include_identity:
        data["index_id"] = index.index_id
    return json.dumps(data, ensure_ascii=False, allow_nan=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def _validate_staged(root: Path, index: FixtureIndex) -> None:
    if (root / FIXTURE_INDEX_FILENAME).read_bytes() != canonical_fixture_index_bytes(index):
        raise EvidencePublicationError("staged fixture index validation failed")
    for entry in index.entries:
        data = (root / entry.path).read_bytes()
        if len(data) != entry.size_bytes or hashlib.sha256(data).hexdigest() != entry.sha256:
            raise EvidencePublicationError("staged fixture validation failed")
