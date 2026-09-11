"""Deterministic bounded serializers and atomic local evidence bundle export."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import stat
import tempfile
from typing import Any, BinaryIO, Iterable, Sequence

from scenario_engine.values import canonical_bytes

from .canonical import canonical_evidence_bytes
from .errors import (
    EvidenceDestinationError,
    EvidenceExportBoundError,
    EvidencePublicationError,
    EvidenceSerializationError,
    EvidenceSourceIntegrityError,
)
from .models import (
    DEFAULT_AGGREGATE_BUNDLE_BYTES,
    MAX_AGGREGATE_BUNDLE_BYTES,
    MAX_ARTIFACT_BYTES,
    MAX_BUNDLE_ENTRIES,
    EvidenceBundle,
    EvidenceEntry,
)
from .read import _open_regular, _open_root, _same_file, read_evidence_bundle


BUNDLE_INDEX_FILENAME = "bundle.json"
MAX_JSONL_RECORDS = MAX_BUNDLE_ENTRIES
_COPY_CHUNK_BYTES = 64 * 1024


def canonical_evidence_records_bytes(
    records: Sequence[Any],
    *,
    max_bytes: int = DEFAULT_AGGREGATE_BUNDLE_BYTES,
) -> bytes:
    """Return a canonical JSON array preserving explicit semantic record order.

    Values use the engine's existing typed semantic normalization. Mapping keys
    are sorted canonically; sequence order is semantic. There is no trailing LF.
    """
    limit = _export_limit(max_bytes)
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes, bytearray)):
        raise TypeError("records must be an explicit ordered sequence")
    values = tuple(records)
    _record_count(len(values))
    try:
        encoded = canonical_bytes(values)
    except (TypeError, ValueError):
        raise EvidenceSerializationError("records contain an unsupported semantic value") from None
    if len(encoded) > limit:
        raise EvidenceExportBoundError(f"canonical JSON exceeds the {limit}-byte export limit")
    return encoded


def write_evidence_jsonl(
    records: Iterable[Any],
    output: BinaryIO,
    *,
    max_bytes: int = DEFAULT_AGGREGATE_BUNDLE_BYTES,
) -> str:
    """Stream caller-ordered semantic records as one canonical value plus LF each.

    The empty stream writes zero bytes. Every non-empty stream has a final LF.
    The returned lowercase SHA-256 identifies the exact bytes written.
    """
    limit = _export_limit(max_bytes)
    if isinstance(records, (str, bytes, bytearray)) or not isinstance(records, Iterable):
        raise TypeError("records must be an iterable of EvidenceEntry values")
    if not hasattr(output, "write"):
        raise TypeError("output must be a binary writable stream")
    digest = hashlib.sha256()
    total = 0
    count = 0
    for record in records:
        count += 1
        _record_count(count)
        try:
            line = canonical_bytes(record) + b"\n"
        except (TypeError, ValueError):
            raise EvidenceSerializationError(
                "records contain an unsupported semantic value"
            ) from None
        if total + len(line) > limit:
            raise EvidenceExportBoundError(f"canonical JSONL exceeds the {limit}-byte export limit")
        try:
            written = output.write(line)
        except (OSError, TypeError, ValueError):
            raise EvidencePublicationError("canonical JSONL output write failed") from None
        if written is not None and written != len(line):
            raise EvidencePublicationError("canonical JSONL output performed a short write")
        digest.update(line)
        total += len(line)
    return digest.hexdigest()


def export_evidence_bundle(
    bundle: EvidenceBundle,
    *,
    source_root: str | os.PathLike[str],
    destination: str | os.PathLike[str],
    max_aggregate_bytes: int = DEFAULT_AGGREGATE_BUNDLE_BYTES,
    chunk_size: int = _COPY_CHUNK_BYTES,
) -> EvidenceBundle:
    """Atomically publish ``bundle`` and unchanged child bytes at ``destination``.

    The destination must be an absent absolute path with an existing safe local
    parent. Source entries are read beneath an explicit absolute root. A complete
    adjacent staging directory is validated with the accepted reader before one
    final directory rename publishes it.
    """
    if not isinstance(bundle, EvidenceBundle):
        raise TypeError("bundle must be an EvidenceBundle")
    limit = _export_limit(max_aggregate_bytes)
    if isinstance(chunk_size, bool) or not isinstance(chunk_size, int) or chunk_size <= 0:
        raise EvidenceExportBoundError("chunk_size must be a positive integer")
    if chunk_size > MAX_ARTIFACT_BYTES:
        raise EvidenceExportBoundError(
            f"chunk_size exceeds the {MAX_ARTIFACT_BYTES}-byte artifact ceiling"
        )
    target, parent = _destination(destination)
    _, source_fd = _open_source_root(source_root)
    staging: Path | None = None
    try:
        # Complete physical and aggregate preflight follows semantic entry order.
        sources: list[tuple[EvidenceEntry, tuple[str, ...], os.stat_result]] = []
        aggregate = 0
        for entry in bundle.entries:
            if entry.path == BUNDLE_INDEX_FILENAME:
                raise EvidenceSourceIntegrityError(
                    f"source evidence entry {entry.logical_id} uses the reserved bundle index path"
                )
            parts = tuple(entry.path.split("/"))
            try:
                fd, metadata = _open_regular(source_fd, parts, f"evidence entry {entry.logical_id}")
            except Exception as exc:
                raise EvidenceSourceIntegrityError(
                    f"source evidence entry {entry.logical_id} cannot be opened safely"
                ) from exc
            os.close(fd)
            if metadata.st_size > MAX_ARTIFACT_BYTES:
                raise EvidenceExportBoundError(
                    f"source evidence entry {entry.logical_id} exceeds the artifact ceiling"
                )
            if metadata.st_size != entry.size_bytes:
                raise EvidenceSourceIntegrityError(
                    f"source evidence entry {entry.logical_id} size does not match"
                )
            aggregate += metadata.st_size
            if aggregate > limit:
                raise EvidenceExportBoundError(
                    f"aggregate evidence bytes exceed the {limit}-byte export limit"
                )
            sources.append((entry, parts, metadata))

        staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.stage-", dir=parent))
        for entry, parts, expected in sources:
            output_path = staging.joinpath(*parts)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            _copy_entry(source_fd, entry, parts, expected, output_path, chunk_size)
        index = staging / BUNDLE_INDEX_FILENAME
        _write_new_regular(index, canonical_evidence_bytes(bundle))
        validated = read_evidence_bundle(
            index, bundle_root=staging, max_aggregate_bytes=limit
        )
        if validated != bundle or validated.bundle_id != bundle.bundle_id:
            raise EvidenceSourceIntegrityError("staged bundle identity does not match")
        try:
            # The adjacent rename is atomic on the parent's filesystem. The
            # earlier lexists gate rejects normal overwrite; a concurrently
            # hostile parent remains the documented filesystem race boundary.
            os.rename(staging, target)
        except FileExistsError:
            raise EvidenceDestinationError("evidence destination already exists") from None
        except OSError:
            raise EvidencePublicationError("atomic evidence bundle publication failed") from None
        staging = None
        return bundle
    finally:
        os.close(source_fd)
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)


def _export_limit(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise EvidenceExportBoundError("export byte limit must be a nonnegative integer")
    if value > MAX_AGGREGATE_BUNDLE_BYTES:
        raise EvidenceExportBoundError(
            f"export byte limit exceeds the {MAX_AGGREGATE_BUNDLE_BYTES}-byte hard ceiling"
        )
    return value


def _record_count(count: int) -> None:
    if count > MAX_JSONL_RECORDS:
        raise EvidenceExportBoundError(
            f"record count exceeds the {MAX_JSONL_RECORDS}-record ceiling"
        )


def _destination(value: str | os.PathLike[str]) -> tuple[Path, Path]:
    if not isinstance(value, (str, os.PathLike)):
        raise TypeError("destination must be a string or path-like value")
    try:
        target = Path(value)
    except (TypeError, ValueError):
        raise EvidenceDestinationError("evidence destination is invalid") from None
    if not target.is_absolute() or target.name in ("", ".", ".."):
        raise EvidenceDestinationError("evidence destination must be an explicit absolute path")
    if os.path.lexists(target):
        raise EvidenceDestinationError("evidence destination already exists")
    parent = target.parent
    _safe_existing_directory(parent, "evidence destination parent")
    return target, parent


def _safe_existing_directory(path: Path, label: str) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            mode = current.lstat().st_mode
        except OSError:
            raise EvidenceDestinationError(f"{label} does not exist or cannot be inspected") from None
        if stat.S_ISLNK(mode):
            raise EvidenceDestinationError(f"{label} contains a symlink")
        if not stat.S_ISDIR(mode):
            raise EvidenceDestinationError(f"{label} must be a directory")


def _open_source_root(value: str | os.PathLike[str]) -> tuple[Path, int]:
    try:
        if not isinstance(value, (str, os.PathLike)):
            raise TypeError
        path = Path(value)
        if not path.is_absolute():
            raise ValueError
        _safe_existing_directory(path, "source root")
        return _open_root(value)
    except Exception as exc:
        raise EvidenceSourceIntegrityError("source root cannot be opened safely") from exc


def _copy_entry(
    source_root_fd: int,
    entry: EvidenceEntry,
    parts: tuple[str, ...],
    expected: os.stat_result,
    output_path: Path,
    chunk_size: int,
) -> None:
    try:
        source_fd, opened = _open_regular(
            source_root_fd, parts, f"evidence entry {entry.logical_id}"
        )
    except Exception as exc:
        raise EvidenceSourceIntegrityError(
            f"source evidence entry {entry.logical_id} cannot be reopened safely"
        ) from exc
    output_fd: int | None = None
    digest = hashlib.sha256()
    total = 0
    try:
        if not _same_file(expected, opened):
            raise EvidenceSourceIntegrityError(
                f"source evidence entry {entry.logical_id} changed during export"
            )
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        output_fd = os.open(output_path, flags, 0o600)
        while True:
            chunk = os.read(source_fd, chunk_size)
            if not chunk:
                break
            digest.update(chunk)
            total += len(chunk)
            _write_all(output_fd, chunk)
        os.fsync(output_fd)
        final = os.fstat(source_fd)
    finally:
        os.close(source_fd)
        if output_fd is not None:
            os.close(output_fd)
    if total != entry.size_bytes or not _same_file(opened, final):
        raise EvidenceSourceIntegrityError(
            f"source evidence entry {entry.logical_id} changed during export"
        )
    if digest.hexdigest() != entry.sha256:
        raise EvidenceSourceIntegrityError(
            f"source evidence entry {entry.logical_id} SHA-256 does not match"
        )


def _write_new_regular(path: Path, data: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, 0o600)
        try:
            _write_all(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        raise EvidencePublicationError("staged evidence index write failed") from None


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise EvidencePublicationError("staged evidence file write failed")
        view = view[written:]
