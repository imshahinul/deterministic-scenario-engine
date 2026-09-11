"""Bounded, offline validation of canonical evidence bundles on local filesystems."""

from __future__ import annotations

import errno
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any

from .canonical import canonical_evidence_bytes
from .errors import (
    EvidenceContractError,
    EvidenceFilesystemError,
    EvidenceIndexError,
    EvidenceIntegrityError,
    EvidenceValidationBoundError,
)
from .models import (
    DEFAULT_AGGREGATE_BUNDLE_BYTES,
    EVIDENCE_BUNDLE_SCHEMA_VERSION,
    EVIDENCE_ENTRY_SCHEMA_VERSION,
    EVIDENCE_PROVENANCE_SCHEMA_VERSION,
    EVIDENCE_RELATIONSHIP_SCHEMA_VERSION,
    MAX_AGGREGATE_BUNDLE_BYTES,
    MAX_ARTIFACT_BYTES,
    MAX_BUNDLE_INDEX_BYTES,
    MAX_BUNDLE_PATH_DEPTH,
    EvidenceBundle,
    EvidenceEntry,
    EvidenceProvenance,
    EvidenceRelationship,
    EvidenceType,
)


MAX_BUNDLE_INDEX_DEPTH = 64
_READ_CHUNK_BYTES = 64 * 1024
_BUNDLE_FIELDS = {"entries", "relationships", "schema_version"}
_ENTRY_FIELDS = {
    "artifact_schema", "evidence_type", "logical_id", "media_type", "path",
    "provenance", "schema_version", "sha256", "size_bytes",
}
_PROVENANCE_FIELDS = {"contract", "schema_version", "source_sha256"}
_RELATIONSHIP_FIELDS = {"kind", "schema_version", "source_id", "target_id"}


def read_evidence_bundle(
    index_path: str | os.PathLike[str],
    *,
    bundle_root: str | os.PathLike[str],
    max_aggregate_bytes: int = DEFAULT_AGGREGATE_BUNDLE_BYTES,
) -> EvidenceBundle:
    """Read and validate one canonical index and all referenced opaque files.

    Both paths are explicit: ``bundle_root`` must be absolute and ``index_path``
    must be an absolute path beneath it. The operation performs no writes,
    discovery, child-schema interpretation, imports selected by data, or execution.
    """
    limit = _aggregate_limit(max_aggregate_bytes)
    root, root_fd = _open_root(bundle_root)
    try:
        index_parts = _relative_parts(index_path, root, "bundle index")
        index_fd, _ = _open_regular(root_fd, index_parts, "bundle index")
        try:
            index_bytes = _read_bounded(index_fd, MAX_BUNDLE_INDEX_BYTES, "bundle index")
        finally:
            os.close(index_fd)
        bundle = _decode_index(index_bytes)

        # Filesystem/type/size gates precede every digest gate. Entries already
        # have the frozen semantic ordering supplied by EvidenceBundle.
        physical: list[tuple[EvidenceEntry, tuple[str, ...], os.stat_result]] = []
        aggregate = 0
        for entry in bundle.entries:
            parts = tuple(entry.path.split("/"))
            fd, metadata = _open_regular(root_fd, parts, f"evidence entry {entry.logical_id}")
            os.close(fd)
            if metadata.st_size > MAX_ARTIFACT_BYTES:
                raise EvidenceValidationBoundError(
                    f"evidence entry {entry.logical_id} exceeds the {MAX_ARTIFACT_BYTES}-byte artifact ceiling"
                )
            if metadata.st_size != entry.size_bytes:
                raise EvidenceIntegrityError(
                    f"evidence entry {entry.logical_id} size does not match size_bytes"
                )
            aggregate += metadata.st_size
            if aggregate > limit:
                raise EvidenceValidationBoundError(
                    f"aggregate evidence bytes exceed the {limit}-byte validation limit"
                )
            physical.append((entry, parts, metadata))

        for entry, parts, expected_metadata in physical:
            fd, opened_metadata = _open_regular(
                root_fd, parts, f"evidence entry {entry.logical_id}"
            )
            try:
                if not _same_file(expected_metadata, opened_metadata):
                    raise EvidenceFilesystemError(
                        f"evidence entry {entry.logical_id} changed during validation"
                    )
                digest, byte_count = _hash_fd(fd)
                final_metadata = os.fstat(fd)
            finally:
                os.close(fd)
            if byte_count != entry.size_bytes or not _same_file(opened_metadata, final_metadata):
                raise EvidenceIntegrityError(
                    f"evidence entry {entry.logical_id} changed during validation"
                )
            if digest != entry.sha256:
                raise EvidenceIntegrityError(
                    f"evidence entry {entry.logical_id} SHA-256 does not match"
                )
        return bundle
    finally:
        os.close(root_fd)


def _aggregate_limit(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise EvidenceValidationBoundError(
            "max_aggregate_bytes must be a nonnegative integer"
        )
    if value > MAX_AGGREGATE_BUNDLE_BYTES:
        raise EvidenceValidationBoundError(
            f"max_aggregate_bytes exceeds the {MAX_AGGREGATE_BUNDLE_BYTES}-byte hard ceiling"
        )
    return value


def _path(value: str | os.PathLike[str], label: str) -> Path:
    if not isinstance(value, (str, os.PathLike)):
        raise TypeError(f"{label} must be a string or path-like value")
    try:
        path = Path(value)
    except (TypeError, ValueError):
        raise EvidenceFilesystemError(f"{label} is invalid") from None
    if not path.is_absolute():
        raise EvidenceFilesystemError(f"{label} must be an explicit absolute path")
    return path


def _open_root(value: str | os.PathLike[str]) -> tuple[Path, int]:
    path = _path(value, "bundle root")
    try:
        mode = path.lstat().st_mode
    except OSError:
        raise EvidenceFilesystemError("bundle root does not exist or cannot be inspected") from None
    if stat.S_ISLNK(mode):
        raise EvidenceFilesystemError("bundle root cannot be a symlink")
    if not stat.S_ISDIR(mode):
        raise EvidenceFilesystemError("bundle root must be a directory")
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        raise EvidenceFilesystemError("bundle root cannot be opened safely") from None
    if not stat.S_ISDIR(os.fstat(fd).st_mode):
        os.close(fd)
        raise EvidenceFilesystemError("bundle root must be a directory")
    return path, fd


def _relative_parts(
    value: str | os.PathLike[str], root: Path, label: str
) -> tuple[str, ...]:
    path = _path(value, label)
    try:
        relative = path.relative_to(root)
    except ValueError:
        raise EvidenceFilesystemError(f"{label} must remain beneath the bundle root") from None
    parts = relative.parts
    if not parts or len(parts) > MAX_BUNDLE_PATH_DEPTH or any(
        part in ("", ".", "..") for part in parts
    ):
        raise EvidenceFilesystemError(f"{label} has an invalid relative path")
    return parts


def _open_regular(
    root_fd: int, parts: tuple[str, ...], label: str
) -> tuple[int, os.stat_result]:
    directory_fd = os.dup(root_fd)
    try:
        for part in parts[:-1]:
            flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
            try:
                next_fd = os.open(part, flags, dir_fd=directory_fd)
            except OSError as exc:
                _raise_open_error(exc, label)
            os.close(directory_fd)
            directory_fd = next_fd
            if not stat.S_ISDIR(os.fstat(directory_fd).st_mode):
                raise EvidenceFilesystemError(f"{label} contains a non-directory component")
        # O_NONBLOCK prevents an attacker-controlled FIFO from blocking before
        # fstat can reject it; it has no effect on ordinary regular-file reads.
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        try:
            fd = os.open(parts[-1], flags, dir_fd=directory_fd)
        except OSError as exc:
            _raise_open_error(exc, label)
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode):
            os.close(fd)
            raise EvidenceFilesystemError(f"{label} must be a regular file")
        return fd, metadata
    finally:
        os.close(directory_fd)


def _raise_open_error(exc: OSError, label: str) -> None:
    if exc.errno in (errno.ELOOP, errno.EMLINK):
        raise EvidenceFilesystemError(f"{label} contains a symlink") from None
    if exc.errno == errno.ENOENT:
        raise EvidenceFilesystemError(f"{label} does not exist") from None
    if exc.errno == errno.ENOTDIR:
        raise EvidenceFilesystemError(
            f"{label} contains a symlink or non-directory component"
        ) from None
    raise EvidenceFilesystemError(f"{label} cannot be opened safely") from None


def _read_bounded(fd: int, limit: int, label: str) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = os.read(fd, min(_READ_CHUNK_BYTES, limit + 1 - total))
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)
        total += len(chunk)
        if total > limit:
            raise EvidenceValidationBoundError(f"{label} exceeds {limit} bytes")


def _decode_index(data: bytes) -> EvidenceBundle:
    if not data:
        raise EvidenceIndexError("bundle index is empty")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise EvidenceIndexError("bundle index JSON must be UTF-8") from None
    try:
        raw = json.loads(text, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (json.JSONDecodeError, ValueError, RecursionError):
        raise EvidenceIndexError("bundle index is not valid strict JSON") from None
    _bound_structure(raw)
    if not isinstance(raw, dict):
        raise EvidenceIndexError("bundle index root must be an object")
    try:
        bundle = _bundle(raw)
    except (EvidenceContractError, EvidenceIndexError):
        raise
    except (TypeError, ValueError, KeyError):
        # Model constructors remain the authority for valid field values, schema
        # versions, identifiers, paths, hashes, counts, and relationship links.
        raise EvidenceIndexError("bundle index contains an invalid structural value") from None
    if canonical_evidence_bytes(bundle) != data:
        raise EvidenceIndexError("bundle index must use canonical evidence JSON bytes")
    return bundle


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_constant(value: str) -> Any:
    raise ValueError(f"non-finite JSON constant is forbidden: {value}")


def _bound_structure(root: Any) -> None:
    stack = [(root, 0)]
    while stack:
        value, depth = stack.pop()
        if depth > MAX_BUNDLE_INDEX_DEPTH:
            raise EvidenceValidationBoundError(
                f"bundle index nesting exceeds {MAX_BUNDLE_INDEX_DEPTH}"
            )
        if isinstance(value, dict):
            stack.extend((item, depth + 1) for item in value.values())
        elif isinstance(value, list):
            stack.extend((item, depth + 1) for item in value)


def _exact(raw: Any, expected: set[str], label: str) -> dict[str, Any]:
    if not isinstance(raw, dict) or set(raw) != expected:
        raise EvidenceIndexError(f"{label} has missing or unknown structural fields")
    return raw


def _bundle(raw: dict[str, Any]) -> EvidenceBundle:
    _exact(raw, _BUNDLE_FIELDS, "bundle index")
    if raw["schema_version"] != EVIDENCE_BUNDLE_SCHEMA_VERSION:
        raise EvidenceIndexError("unsupported evidence bundle schema version")
    if not isinstance(raw["entries"], list) or not isinstance(raw["relationships"], list):
        raise EvidenceIndexError("bundle entries and relationships must be arrays")
    entries = tuple(_entry(item) for item in raw["entries"])
    relationships = tuple(_relationship(item) for item in raw["relationships"])
    return EvidenceBundle(entries, relationships, raw["schema_version"])


def _entry(raw: Any) -> EvidenceEntry:
    value = _exact(raw, _ENTRY_FIELDS, "evidence entry")
    provenance = value["provenance"]
    return EvidenceEntry(
        logical_id=value["logical_id"],
        evidence_type=EvidenceType(value["evidence_type"]),
        artifact_schema=value["artifact_schema"],
        media_type=value["media_type"],
        path=value["path"],
        sha256=value["sha256"],
        size_bytes=value["size_bytes"],
        provenance=None if provenance is None else _provenance(provenance),
        schema_version=value["schema_version"],
    )


def _provenance(raw: Any) -> EvidenceProvenance:
    value = _exact(raw, _PROVENANCE_FIELDS, "evidence provenance")
    if value["schema_version"] != EVIDENCE_PROVENANCE_SCHEMA_VERSION:
        raise EvidenceIndexError("unsupported evidence provenance schema version")
    return EvidenceProvenance(
        source_sha256=value["source_sha256"],
        contract=value["contract"],
        schema_version=value["schema_version"],
    )


def _relationship(raw: Any) -> EvidenceRelationship:
    value = _exact(raw, _RELATIONSHIP_FIELDS, "evidence relationship")
    if value["schema_version"] != EVIDENCE_RELATIONSHIP_SCHEMA_VERSION:
        raise EvidenceIndexError("unsupported evidence relationship schema version")
    return EvidenceRelationship(
        source_id=value["source_id"], target_id=value["target_id"],
        kind=value["kind"], schema_version=value["schema_version"],
    )


def _hash_fd(fd: int) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    while True:
        chunk = os.read(fd, _READ_CHUNK_BYTES)
        if not chunk:
            return digest.hexdigest(), total
        digest.update(chunk)
        total += len(chunk)


def _same_file(first: os.stat_result, second: os.stat_result) -> bool:
    return (
        first.st_dev,
        first.st_ino,
        first.st_mode,
        first.st_size,
        first.st_mtime_ns,
    ) == (
        second.st_dev,
        second.st_ino,
        second.st_mode,
        second.st_size,
        second.st_mtime_ns,
    )
