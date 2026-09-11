from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import time
from unittest.mock import patch

import pytest

from scenario_engine.evidence import (
    MAX_AGGREGATE_BUNDLE_BYTES,
    MAX_ARTIFACT_BYTES,
    MAX_BUNDLE_INDEX_BYTES,
    EvidenceBundle,
    EvidenceContractError,
    EvidenceEntry,
    EvidenceFilesystemError,
    EvidenceIndexError,
    EvidenceIntegrityError,
    EvidenceRelationship,
    EvidenceType,
    EvidenceValidationBoundError,
    canonical_evidence_bytes,
    read_evidence_bundle,
)


def _entry(logical_id: str, path: str, data: bytes) -> EvidenceEntry:
    return EvidenceEntry(
        logical_id=logical_id,
        evidence_type=EvidenceType.RESULT,
        artifact_schema="suite.run/1",
        media_type="application/json",
        path=path,
        sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
    )


def _materialize(root: Path, entries: list[tuple[str, str, bytes]], relationships=()) -> tuple[Path, EvidenceBundle]:
    models = []
    for logical_id, relative, data in entries:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        models.append(_entry(logical_id, relative, data))
    bundle = EvidenceBundle(tuple(models), tuple(relationships))
    index = root / "evidence-index.json"
    index.write_bytes(canonical_evidence_bytes(bundle))
    return index, bundle


def _raw_index(root: Path, data: bytes) -> Path:
    path = root / "index.json"
    path.write_bytes(data)
    return path


def test_minimal_multiple_relationship_and_repeat_validation(tmp_path: Path) -> None:
    relationship = EvidenceRelationship("result:b", "result:a", "derived-from")
    index, expected = _materialize(
        tmp_path,
        [("result:b", "results/b.json", b'{"b":2}'), ("result:a", "results/a.json", b'{"a":1}')],
        (relationship,),
    )

    first = read_evidence_bundle(index, bundle_root=tmp_path)
    second = read_evidence_bundle(index, bundle_root=tmp_path)

    assert first == second == expected
    assert tuple(entry.logical_id for entry in first.entries) == ("result:a", "result:b")
    assert first.relationships == (relationship,)


@pytest.mark.parametrize(
    ("data", "error", "message"),
    [
        (b"", EvidenceIndexError, "empty"),
        (b"{", EvidenceIndexError, "strict JSON"),
        (b"[]", EvidenceIndexError, "root must be an object"),
        (b"\xff", EvidenceIndexError, "UTF-8"),
        (b'{"entries":[],"entries":[],"relationships":[],"schema_version":"evidence.bundle/1"}', EvidenceIndexError, "strict JSON"),
        (b'{"entries":[],"relationships":[],"schema_version":"evidence.bundle/2"}', EvidenceIndexError, "unsupported"),
        (b'{"entries":[],"schema_version":"evidence.bundle/1"}', EvidenceIndexError, "structural"),
    ],
)
def test_index_parser_failures(tmp_path: Path, data: bytes, error: type[Exception], message: str) -> None:
    with pytest.raises(error, match=message):
        read_evidence_bundle(_raw_index(tmp_path, data), bundle_root=tmp_path)


def test_noncanonical_and_invalid_model_index_fail_closed(tmp_path: Path) -> None:
    canonical = canonical_evidence_bytes(EvidenceBundle(()))
    noncanonical = json.dumps(json.loads(canonical), indent=2).encode()
    with pytest.raises(EvidenceIndexError, match="canonical"):
        read_evidence_bundle(_raw_index(tmp_path, noncanonical), bundle_root=tmp_path)

    raw = json.loads(canonical)
    raw["entries"] = [{
        "artifact_schema": "suite.run/1", "evidence_type": "result", "logical_id": "bad id",
        "media_type": "application/json", "path": "a.json", "provenance": None,
        "schema_version": "evidence.entry/1", "sha256": "0" * 64, "size_bytes": 0,
    }]
    with pytest.raises(EvidenceContractError, match="logical_id"):
        read_evidence_bundle(_raw_index(tmp_path, json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()), bundle_root=tmp_path)


def test_index_byte_and_depth_bounds(tmp_path: Path) -> None:
    index = _raw_index(tmp_path, b"x")
    with patch("scenario_engine.evidence.read.MAX_BUNDLE_INDEX_BYTES", 0):
        with pytest.raises(EvidenceValidationBoundError, match="bundle index exceeds"):
            read_evidence_bundle(index, bundle_root=tmp_path)

    nested: object = 0
    for _ in range(66):
        nested = [nested]
    with patch("scenario_engine.evidence.read.MAX_BUNDLE_INDEX_BYTES", MAX_BUNDLE_INDEX_BYTES):
        with pytest.raises(EvidenceValidationBoundError, match="nesting"):
            read_evidence_bundle(_raw_index(tmp_path, json.dumps(nested).encode()), bundle_root=tmp_path)


def test_root_and_index_must_be_explicit_absolute_and_contained(tmp_path: Path) -> None:
    index, _ = _materialize(tmp_path, [])
    with pytest.raises(EvidenceFilesystemError, match="bundle root must be an explicit absolute"):
        read_evidence_bundle(index, bundle_root="relative")
    with pytest.raises(EvidenceFilesystemError, match="bundle index must be an explicit absolute"):
        read_evidence_bundle("index.json", bundle_root=tmp_path)
    outside = tmp_path.parent / "outside-index.json"
    outside.write_bytes(canonical_evidence_bytes(EvidenceBundle(())))
    try:
        with pytest.raises(EvidenceFilesystemError, match="beneath"):
            read_evidence_bundle(outside, bundle_root=tmp_path)
    finally:
        outside.unlink()


def test_missing_directory_and_lexically_unsafe_paths(tmp_path: Path) -> None:
    data = b"ok"
    index, bundle = _materialize(tmp_path, [("result:a", "a.json", data)])
    (tmp_path / "a.json").unlink()
    with pytest.raises(EvidenceFilesystemError, match="does not exist"):
        read_evidence_bundle(index, bundle_root=tmp_path)

    (tmp_path / "a.json").mkdir()
    with pytest.raises(EvidenceFilesystemError, match="regular file"):
        read_evidence_bundle(index, bundle_root=tmp_path)

    for unsafe in ("/x", "../x", "a\\b", "https://host/x", "a\x00b"):
        raw = json.loads(canonical_evidence_bytes(bundle))
        raw["entries"][0]["path"] = unsafe
        encoded = json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()
        with pytest.raises(EvidenceContractError, match="path"):
            read_evidence_bundle(_raw_index(tmp_path, encoded), bundle_root=tmp_path)


def test_symlinked_file_parent_broken_link_and_root_are_rejected(tmp_path: Path) -> None:
    outside = tmp_path.parent / "phase3-2-outside"
    outside.mkdir()
    try:
        (outside / "data.json").write_bytes(b"opaque")

        file_root = tmp_path / "file-link"
        file_root.mkdir()
        index, _ = _materialize(file_root, [("result:a", "data.json", b"opaque")])
        (file_root / "data.json").unlink()
        (file_root / "data.json").symlink_to(outside / "data.json")
        with pytest.raises(EvidenceFilesystemError, match="symlink"):
            read_evidence_bundle(index, bundle_root=file_root)

        parent_root = tmp_path / "parent-link"
        parent_root.mkdir()
        model = EvidenceBundle((_entry("result:a", "linked/data.json", b"opaque"),))
        parent_index = parent_root / "index.json"
        parent_index.write_bytes(canonical_evidence_bytes(model))
        (parent_root / "linked").symlink_to(outside, target_is_directory=True)
        with pytest.raises(EvidenceFilesystemError, match="symlink"):
            read_evidence_bundle(parent_index, bundle_root=parent_root)

        broken_root = tmp_path / "broken"
        broken_root.mkdir()
        broken_model = EvidenceBundle((_entry("result:a", "missing.json", b"opaque"),))
        broken_index = broken_root / "index.json"
        broken_index.write_bytes(canonical_evidence_bytes(broken_model))
        (broken_root / "missing.json").symlink_to(broken_root / "absent")
        with pytest.raises(EvidenceFilesystemError, match="symlink"):
            read_evidence_bundle(broken_index, bundle_root=broken_root)

        root_link = tmp_path / "root-link"
        root_link.symlink_to(file_root, target_is_directory=True)
        with pytest.raises(EvidenceFilesystemError, match="root cannot be a symlink"):
            read_evidence_bundle(index, bundle_root=root_link)
    finally:
        for child in outside.iterdir():
            child.unlink()
        outside.rmdir()


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="platform cannot construct a FIFO")
def test_special_file_is_rejected_without_reading_it(tmp_path: Path) -> None:
    fifo = tmp_path / "pipe"
    os.mkfifo(fifo)
    model = EvidenceBundle((_entry("result:a", "pipe", b""),))
    index = tmp_path / "index.json"
    index.write_bytes(canonical_evidence_bytes(model))
    with pytest.raises(EvidenceFilesystemError, match="regular file"):
        read_evidence_bundle(index, bundle_root=tmp_path)


def test_size_aggregate_individual_digest_and_changed_bytes(tmp_path: Path) -> None:
    index, _ = _materialize(tmp_path, [("result:a", "a", b"abc"), ("result:b", "b", b"de")])
    with pytest.raises(EvidenceValidationBoundError, match="aggregate"):
        read_evidence_bundle(index, bundle_root=tmp_path, max_aggregate_bytes=4)
    for invalid in (-1, True, 1.5, MAX_AGGREGATE_BUNDLE_BYTES + 1):
        with pytest.raises(EvidenceValidationBoundError, match="max_aggregate_bytes"):
            read_evidence_bundle(index, bundle_root=tmp_path, max_aggregate_bytes=invalid)  # type: ignore[arg-type]

    raw = json.loads(index.read_bytes())
    raw["entries"][0]["size_bytes"] = 2
    bad_size = _raw_index(tmp_path, json.dumps(raw, sort_keys=True, separators=(",", ":")).encode())
    with pytest.raises(EvidenceIntegrityError, match="size"):
        read_evidence_bundle(bad_size, bundle_root=tmp_path)

    raw = json.loads(index.read_bytes())
    raw["entries"][0]["sha256"] = "0" * 64
    bad_hash = _raw_index(tmp_path, json.dumps(raw, sort_keys=True, separators=(",", ":")).encode())
    with pytest.raises(EvidenceIntegrityError, match="SHA-256"):
        read_evidence_bundle(bad_hash, bundle_root=tmp_path)

    (tmp_path / "a").write_bytes(b"changed")
    with pytest.raises(EvidenceIntegrityError, match="size"):
        read_evidence_bundle(index, bundle_root=tmp_path)

    (tmp_path / "a").write_bytes(b"xyz")
    with pytest.raises(EvidenceIntegrityError, match="SHA-256"):
        read_evidence_bundle(index, bundle_root=tmp_path)

    with patch("scenario_engine.evidence.read.MAX_ARTIFACT_BYTES", 1):
        with pytest.raises(EvidenceValidationBoundError, match="artifact ceiling"):
            read_evidence_bundle(index, bundle_root=tmp_path, max_aggregate_bytes=10)


def test_failure_precedence_uses_semantic_entry_order(tmp_path: Path) -> None:
    model = EvidenceBundle((
        _entry("result:z", "z", b"z"),
        _entry("result:a", "a", b"a"),
    ))
    index = tmp_path / "index.json"
    index.write_bytes(canonical_evidence_bytes(model))
    with pytest.raises(EvidenceFilesystemError, match="result:a"):
        read_evidence_bundle(index, bundle_root=tmp_path)


def test_reader_has_no_execution_discovery_network_subprocess_or_ambient_semantics(tmp_path: Path) -> None:
    data = b'{"plugin":"evil.module","domain_pack":"evil.pack","assertion":"execute"}'
    index, _ = _materialize(tmp_path, [("result:a", "opaque.json", data)])
    original_environ = dict(os.environ)
    with (
        patch.object(time, "time", side_effect=AssertionError("clock accessed")),
        patch("random.random", side_effect=AssertionError("randomness accessed")),
        patch.object(socket, "create_connection", side_effect=AssertionError("network accessed")),
        patch.object(socket.socket, "connect", side_effect=AssertionError("socket accessed")),
        patch.object(subprocess, "run", side_effect=AssertionError("subprocess accessed")),
        patch("builtins.__import__", wraps=__import__) as importer,
    ):
        assert read_evidence_bundle(index, bundle_root=tmp_path).entries[0].path == "opaque.json"
    assert dict(os.environ) == original_environ
    imported = [str(call.args[0]) for call in importer.mock_calls if call.args]
    assert "evil.module" not in imported and "evil.pack" not in imported


def test_reader_streams_artifact_hashing(tmp_path: Path) -> None:
    index, _ = _materialize(tmp_path, [("result:a", "artifact", b"x" * 200_000)])
    real_read = os.read
    sizes = []

    def recording_read(fd: int, size: int) -> bytes:
        sizes.append(size)
        return real_read(fd, size)

    with patch("scenario_engine.evidence.read.os.read", side_effect=recording_read):
        read_evidence_bundle(index, bundle_root=tmp_path)
    assert max(sizes) <= 64 * 1024
