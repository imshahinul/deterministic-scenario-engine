"""Immutable models defining the versioned canonical evidence bundle index."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Any, Sequence
from urllib.parse import urlsplit

from .errors import EvidenceBoundError, EvidenceContractError


EVIDENCE_BUNDLE_SCHEMA_VERSION = "evidence.bundle/1"
EVIDENCE_ENTRY_SCHEMA_VERSION = "evidence.entry/1"
EVIDENCE_RELATIONSHIP_SCHEMA_VERSION = "evidence.relationship/1"
EVIDENCE_PROVENANCE_SCHEMA_VERSION = "evidence.provenance/1"

MAX_BUNDLE_ENTRIES = 100_000
MAX_BUNDLE_RELATIONSHIPS = 100_000
MAX_BUNDLE_INDEX_BYTES = 16 * 1024 * 1024
MAX_ARTIFACT_BYTES = 256 * 1024 * 1024
MAX_BUNDLE_PATH_DEPTH = 64
DEFAULT_AGGREGATE_BUNDLE_BYTES = 256 * 1024 * 1024
MAX_AGGREGATE_BUNDLE_BYTES = 4 * 1024 * 1024 * 1024

_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@/-]{0,255}\Z")
_CONTRACT = re.compile(r"[a-z][a-z0-9._-]*/[1-9][0-9]*\Z")
_MEDIA_TYPE = re.compile(
    r"[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*\Z"
)
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_DRIVE = re.compile(r"[A-Za-z]:")


def _identifier(value: Any, name: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise EvidenceContractError(f"{name} must be a portable ASCII identifier")
    return value


def _contract(value: Any, name: str) -> str:
    if not isinstance(value, str) or _CONTRACT.fullmatch(value) is None:
        raise EvidenceContractError(f"{name} must be a versioned contract identifier")
    return value


def _sha256(value: Any, name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise EvidenceContractError(
            f"{name} must be a lowercase SHA-256 hexadecimal string"
        )
    return value


def _nonnegative_size(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise EvidenceContractError("size_bytes must be a nonnegative integer")
    if value > MAX_ARTIFACT_BYTES:
        raise EvidenceBoundError(
            f"size_bytes exceeds the {MAX_ARTIFACT_BYTES}-byte artifact ceiling"
        )
    return value


def _relative_posix_path(value: Any) -> str:
    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        raise EvidenceContractError("path must be a non-empty relative POSIX path")
    if value.startswith(("/", "//")) or _DRIVE.match(value):
        raise EvidenceContractError("path must not be absolute, UNC, or drive-qualified")
    if urlsplit(value).scheme:
        raise EvidenceContractError("path must not contain a URI scheme")
    parts = value.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise EvidenceContractError("path contains an empty, dot, or parent segment")
    if len(parts) > MAX_BUNDLE_PATH_DEPTH:
        raise EvidenceBoundError(
            f"path exceeds the {MAX_BUNDLE_PATH_DEPTH}-segment depth ceiling"
        )
    return value


class EvidenceType(str, Enum):
    """Architecture-authorized logical evidence categories."""

    MANIFEST = "manifest"
    RESULT = "result"
    EVALUATION = "evaluation"
    INSPECTION = "inspection"
    DIFF = "diff"


@dataclass(frozen=True, slots=True)
class EvidenceProvenance:
    """A pure reference to the canonical source and producing contract."""

    source_sha256: str
    contract: str
    schema_version: str = EVIDENCE_PROVENANCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != EVIDENCE_PROVENANCE_SCHEMA_VERSION:
            raise EvidenceContractError("unsupported evidence provenance schema version")
        object.__setattr__(self, "source_sha256", _sha256(self.source_sha256, "source_sha256"))
        object.__setattr__(self, "contract", _contract(self.contract, "contract"))


@dataclass(frozen=True, slots=True)
class EvidenceEntry:
    """One logical artifact in the deterministic bundle index."""

    logical_id: str
    evidence_type: EvidenceType
    artifact_schema: str
    media_type: str
    path: str
    sha256: str
    size_bytes: int
    provenance: EvidenceProvenance | None = None
    schema_version: str = EVIDENCE_ENTRY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != EVIDENCE_ENTRY_SCHEMA_VERSION:
            raise EvidenceContractError("unsupported evidence entry schema version")
        object.__setattr__(self, "logical_id", _identifier(self.logical_id, "logical_id"))
        if not isinstance(self.evidence_type, EvidenceType):
            raise EvidenceContractError("evidence_type must be an EvidenceType")
        object.__setattr__(self, "artifact_schema", _contract(self.artifact_schema, "artifact_schema"))
        if not isinstance(self.media_type, str) or _MEDIA_TYPE.fullmatch(self.media_type) is None:
            raise EvidenceContractError("media_type must be a lowercase media type")
        object.__setattr__(self, "path", _relative_posix_path(self.path))
        object.__setattr__(self, "sha256", _sha256(self.sha256, "sha256"))
        object.__setattr__(self, "size_bytes", _nonnegative_size(self.size_bytes))
        if self.provenance is not None and not isinstance(self.provenance, EvidenceProvenance):
            raise EvidenceContractError("provenance must be EvidenceProvenance or None")


@dataclass(frozen=True, slots=True)
class EvidenceRelationship:
    """A declarative directed relationship between two logical entries."""

    source_id: str
    target_id: str
    kind: str
    schema_version: str = EVIDENCE_RELATIONSHIP_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != EVIDENCE_RELATIONSHIP_SCHEMA_VERSION:
            raise EvidenceContractError("unsupported evidence relationship schema version")
        object.__setattr__(self, "source_id", _identifier(self.source_id, "source_id"))
        object.__setattr__(self, "target_id", _identifier(self.target_id, "target_id"))
        object.__setattr__(self, "kind", _identifier(self.kind, "kind"))
        if self.source_id == self.target_id:
            raise EvidenceContractError("relationship source and target must differ")


def _sequence(value: Any, expected: type[Any], name: str) -> tuple[Any, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise EvidenceContractError(f"{name} must be an explicit ordered sequence")
    result = tuple(value)
    if not all(isinstance(item, expected) for item in result):
        raise EvidenceContractError(f"{name} contains an invalid model")
    return result


@dataclass(frozen=True, slots=True)
class EvidenceBundle:
    """The canonical, finite evidence bundle index and its content identity."""

    entries: tuple[EvidenceEntry, ...]
    relationships: tuple[EvidenceRelationship, ...] = ()
    schema_version: str = EVIDENCE_BUNDLE_SCHEMA_VERSION
    bundle_id: str = field(init=False)

    def __post_init__(self) -> None:
        if self.schema_version != EVIDENCE_BUNDLE_SCHEMA_VERSION:
            raise EvidenceContractError("unsupported evidence bundle schema version")
        entries = _sequence(self.entries, EvidenceEntry, "entries")
        if len(entries) > MAX_BUNDLE_ENTRIES:
            raise EvidenceBoundError(
                f"entries exceeds the {MAX_BUNDLE_ENTRIES}-entry ceiling"
            )
        logical_ids = [item.logical_id for item in entries]
        if len(logical_ids) != len(set(logical_ids)):
            raise EvidenceContractError("entries contains a duplicate logical_id")
        paths = [item.path for item in entries]
        if len(paths) != len(set(paths)):
            raise EvidenceContractError("entries contains a duplicate path")
        if len(paths) != len({path.casefold() for path in paths}):
            raise EvidenceContractError("entries contains a case-fold path collision")
        entries = tuple(sorted(entries, key=lambda item: item.logical_id))

        relationships = _sequence(
            self.relationships, EvidenceRelationship, "relationships"
        )
        if len(relationships) > MAX_BUNDLE_RELATIONSHIPS:
            raise EvidenceBoundError(
                "relationships exceeds the bounded relationship ceiling"
            )
        targets = set(logical_ids)
        for relationship in relationships:
            if relationship.source_id not in targets or relationship.target_id not in targets:
                raise EvidenceContractError("relationship references an unknown logical_id")
        relation_keys = [
            (item.source_id, item.kind, item.target_id) for item in relationships
        ]
        if len(relation_keys) != len(set(relation_keys)):
            raise EvidenceContractError("relationships contains a duplicate relationship")
        relationships = tuple(sorted(
            relationships,
            key=lambda item: (item.source_id, item.kind, item.target_id),
        ))

        object.__setattr__(self, "entries", entries)
        object.__setattr__(self, "relationships", relationships)
        from .canonical import _model_identity, canonical_evidence_bytes

        object.__setattr__(self, "bundle_id", _model_identity(self))
        size = len(canonical_evidence_bytes(self))
        if size > MAX_BUNDLE_INDEX_BYTES:
            raise EvidenceBoundError(
                f"canonical index exceeds the {MAX_BUNDLE_INDEX_BYTES}-byte ceiling"
            )
