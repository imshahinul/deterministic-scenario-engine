from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import io
import os
from pathlib import Path
import socket
import subprocess
import time
from unittest.mock import patch

import pytest

from scenario_engine.evidence import (
    BUNDLE_INDEX_FILENAME,
    MAX_AGGREGATE_BUNDLE_BYTES,
    EvidenceBundle,
    EvidenceDestinationError,
    EvidenceEntry,
    EvidenceExportBoundError,
    EvidenceProvenance,
    EvidenceRelationship,
    EvidenceSerializationError,
    EvidenceSourceIntegrityError,
    EvidenceType,
    canonical_evidence_bytes,
    canonical_evidence_records_bytes,
    export_evidence_bundle,
    read_evidence_bundle,
    write_evidence_jsonl,
)


def _entry(logical_id: str, path: str, data: bytes, *, provenance=None) -> EvidenceEntry:
    return EvidenceEntry(
        logical_id=logical_id,
        evidence_type=EvidenceType.RESULT,
        artifact_schema="suite.run/1",
        media_type="application/json",
        path=path,
        sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
        provenance=provenance,
    )


def _source(tmp_path: Path, values: list[tuple[str, str, bytes]], relationships=()) -> tuple[Path, EvidenceBundle]:
    root = tmp_path / "source"
    root.mkdir()
    entries = []
    for logical_id, relative, data in values:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        entries.append(_entry(logical_id, relative, data))
    return root, EvidenceBundle(tuple(entries), tuple(relationships))


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*")) if path.is_file()
    }


def test_canonical_json_empty_golden_order_and_mapping_permutation_identity() -> None:
    assert canonical_evidence_records_bytes(()) == b"[]"
    expected = b'[{"a":1,"b":2},{"kind":"second"}]'
    assert canonical_evidence_records_bytes(({"b": 2, "a": 1}, {"kind": "second"})) == expected
    assert canonical_evidence_records_bytes(({"a": 1, "b": 2}, {"kind": "second"})) == expected
    assert canonical_evidence_records_bytes(({"kind": "second"}, {"a": 1, "b": 2})) != expected


def test_canonical_json_rejects_unsupported_values_and_bounds() -> None:
    with pytest.raises(EvidenceSerializationError, match="unsupported"):
        canonical_evidence_records_bytes((object(),))  # type: ignore[arg-type]
    with pytest.raises(EvidenceExportBoundError, match="canonical JSON"):
        canonical_evidence_records_bytes(({"a": 1},), max_bytes=1)
    for invalid in (-1, True, 1.5, MAX_AGGREGATE_BUNDLE_BYTES + 1):
        with pytest.raises(EvidenceExportBoundError, match="limit"):
            canonical_evidence_records_bytes((), max_bytes=invalid)  # type: ignore[arg-type]


def test_jsonl_golden_newlines_order_empty_and_digest() -> None:
    output = io.BytesIO()
    digest = write_evidence_jsonl(({"z": 1}, {"a": 2}), output)
    expected = b'{"z":1}\n{"a":2}\n'
    assert output.getvalue() == expected
    assert expected.count(b"\n") == 2 and expected.endswith(b"\n")
    assert digest == hashlib.sha256(expected).hexdigest()
    empty = io.BytesIO()
    assert write_evidence_jsonl((), empty) == hashlib.sha256(b"").hexdigest()
    assert empty.getvalue() == b""


def test_jsonl_streams_once_preserves_order_and_enforces_bounds() -> None:
    entries = [{"name": name} for name in ("z", "a", "m")]
    seen = []

    def stream():
        for entry in entries:
            seen.append(entry["name"])
            yield entry

    first, second = io.BytesIO(), io.BytesIO()
    write_evidence_jsonl(stream(), first)
    write_evidence_jsonl(iter(entries), second)
    assert first.getvalue() == second.getvalue()
    assert seen == ["z", "a", "m"]
    with pytest.raises(EvidenceExportBoundError, match="JSONL"):
        write_evidence_jsonl(entries, io.BytesIO(), max_bytes=1)
    with patch("scenario_engine.evidence.export.MAX_JSONL_RECORDS", 1):
        with pytest.raises(EvidenceExportBoundError, match="record count"):
            write_evidence_jsonl(entries, io.BytesIO())


def test_bundle_round_trip_identity_relationship_provenance_and_opaque_bytes(tmp_path: Path) -> None:
    values = [("result:b", "results/b.json", b'{ "opaque" : 2 }\n'), ("result:a", "results/a.json", b"\x00opaque\xff")]
    root, base = _source(tmp_path, values)
    provenance = EvidenceProvenance(base.entries[0].sha256, "evidence.export/1")
    entries = tuple(
        _entry(entry.logical_id, entry.path, (root / entry.path).read_bytes(), provenance=provenance if entry.logical_id == "result:a" else None)
        for entry in base.entries
    )
    relationship = EvidenceRelationship("result:b", "result:a", "derived-from")
    bundle = EvidenceBundle(entries, (relationship,))
    destination = tmp_path / "bundle"

    returned = export_evidence_bundle(bundle, source_root=root, destination=destination)
    read = read_evidence_bundle(destination / BUNDLE_INDEX_FILENAME, bundle_root=destination)

    assert returned == read == bundle
    assert read.bundle_id == bundle.bundle_id
    assert (destination / BUNDLE_INDEX_FILENAME).read_bytes() == canonical_evidence_bytes(bundle)
    for _, relative, data in values:
        assert (destination / relative).read_bytes() == data


def test_repeated_bundle_exports_and_chunk_sizes_are_byte_identical(tmp_path: Path) -> None:
    root, bundle = _source(tmp_path, [("result:a", "results/a", b"0123456789" * 1000)])
    one, two = tmp_path / "one", tmp_path / "two"
    export_evidence_bundle(bundle, source_root=root, destination=one, chunk_size=1)
    export_evidence_bundle(bundle, source_root=root, destination=two, chunk_size=997)
    assert _tree_bytes(one) == _tree_bytes(two)


def test_existing_relative_missing_and_symlinked_destination_are_rejected(tmp_path: Path) -> None:
    root, bundle = _source(tmp_path, [])
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(EvidenceDestinationError, match="exists"):
        export_evidence_bundle(bundle, source_root=root, destination=existing)
    with pytest.raises(EvidenceDestinationError, match="absolute"):
        export_evidence_bundle(bundle, source_root=root, destination="relative")
    missing = tmp_path / "missing" / "bundle"
    with pytest.raises(EvidenceDestinationError, match="does not exist"):
        export_evidence_bundle(bundle, source_root=root, destination=missing)
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    with pytest.raises(EvidenceDestinationError, match="symlink"):
        export_evidence_bundle(bundle, source_root=root, destination=linked_parent / "bundle")


def test_source_size_digest_symlink_and_special_file_fail_without_publication(tmp_path: Path) -> None:
    root, bundle = _source(tmp_path, [("result:a", "a", b"abc")])
    destination = tmp_path / "destination"
    (root / "a").write_bytes(b"changed")
    with pytest.raises(EvidenceSourceIntegrityError, match="size"):
        export_evidence_bundle(bundle, source_root=root, destination=destination)
    assert not destination.exists()
    (root / "a").write_bytes(b"xyz")
    with pytest.raises(EvidenceSourceIntegrityError, match="SHA-256"):
        export_evidence_bundle(bundle, source_root=root, destination=destination)
    (root / "a").unlink()
    outside = tmp_path / "outside"
    outside.write_bytes(b"abc")
    (root / "a").symlink_to(outside)
    with pytest.raises(EvidenceSourceIntegrityError, match="opened safely"):
        export_evidence_bundle(bundle, source_root=root, destination=destination)
    assert not destination.exists()

    if hasattr(os, "mkfifo"):
        (root / "a").unlink()
        os.mkfifo(root / "a")
        with pytest.raises(EvidenceSourceIntegrityError, match="opened safely"):
            export_evidence_bundle(bundle, source_root=root, destination=destination)


def test_relative_and_symlinked_source_root_are_rejected(tmp_path: Path) -> None:
    root, bundle = _source(tmp_path, [])
    destination = tmp_path / "destination"
    with pytest.raises(EvidenceSourceIntegrityError, match="source root"):
        export_evidence_bundle(bundle, source_root="relative", destination=destination)
    linked = tmp_path / "linked-source"
    linked.symlink_to(root, target_is_directory=True)
    with pytest.raises(EvidenceSourceIntegrityError, match="source root"):
        export_evidence_bundle(bundle, source_root=linked, destination=destination)


def test_aggregate_individual_chunk_and_staging_cleanup_bounds(tmp_path: Path) -> None:
    root, bundle = _source(tmp_path, [("result:a", "a", b"abc"), ("result:b", "b", b"de")])
    destination = tmp_path / "destination"
    with pytest.raises(EvidenceExportBoundError, match="aggregate"):
        export_evidence_bundle(bundle, source_root=root, destination=destination, max_aggregate_bytes=4)
    assert not destination.exists() and not list(tmp_path.glob(".destination.stage-*"))
    with pytest.raises(EvidenceExportBoundError, match="chunk_size"):
        export_evidence_bundle(bundle, source_root=root, destination=destination, chunk_size=0)
    with patch("scenario_engine.evidence.export.MAX_ARTIFACT_BYTES", 1):
        with pytest.raises(EvidenceExportBoundError, match="artifact ceiling"):
            export_evidence_bundle(bundle, source_root=root, destination=destination)


def test_publication_failure_cleans_stage_and_never_exposes_destination(tmp_path: Path) -> None:
    root, bundle = _source(tmp_path, [("result:a", "a", b"abc")])
    destination = tmp_path / "destination"
    with patch("scenario_engine.evidence.export.read_evidence_bundle", side_effect=EvidenceSourceIntegrityError("forced")):
        with pytest.raises(EvidenceSourceIntegrityError, match="forced"):
            export_evidence_bundle(bundle, source_root=root, destination=destination)
    assert not destination.exists()
    assert not list(tmp_path.glob(".destination.stage-*"))


def test_export_has_no_execution_discovery_network_subprocess_or_ambient_semantics(tmp_path: Path) -> None:
    root, bundle = _source(tmp_path, [("result:evil.module", "opaque", b"evil.pack assertion")])
    destination = tmp_path / "destination"
    environment = dict(os.environ)
    with (
        patch.object(time, "time", side_effect=AssertionError("semantic clock accessed")),
        patch("random.random", side_effect=AssertionError("randomness accessed")),
        patch.object(socket, "create_connection", side_effect=AssertionError("network accessed")),
        patch.object(socket.socket, "connect", side_effect=AssertionError("socket accessed")),
        patch.object(subprocess, "run", side_effect=AssertionError("subprocess accessed")),
        patch("builtins.__import__", wraps=__import__) as importer,
    ):
        export_evidence_bundle(bundle, source_root=root, destination=destination)
    assert dict(os.environ) == environment
    imported = [str(call.args[0]) for call in importer.mock_calls if call.args]
    assert "evil.module" not in imported and "evil.pack" not in imported


def test_existing_semantic_types_are_canonical_without_lossy_stringification() -> None:
    from scenario_engine.values import MISSING

    value = {"decimal": Decimal("1.20"), "when": datetime(2026, 1, 1, tzinfo=timezone.utc), "missing": MISSING}
    expected = (
        b'[{"decimal":{"$type":"decimal","value":"1.20"},'
        b'"missing":{"$type":"missing"},"when":{"$type":"datetime",'
        b'"value":"2026-01-01T00:00:00.000000+00:00"}}]'
    )
    assert canonical_evidence_records_bytes((value,)) == expected
    output = io.BytesIO()
    write_evidence_jsonl((value,), output)
    assert output.getvalue() == expected[1:-1] + b"\n"
    with pytest.raises(EvidenceSerializationError, match="unsupported"):
        canonical_evidence_records_bytes(({"unsupported": object()},))


def test_reserved_index_entry_path_is_rejected(tmp_path: Path) -> None:
    root, bundle = _source(tmp_path, [("result:a", BUNDLE_INDEX_FILENAME, b"opaque")])
    destination = tmp_path / "destination"
    with pytest.raises(EvidenceSourceIntegrityError, match="reserved"):
        export_evidence_bundle(bundle, source_root=root, destination=destination)
    assert not destination.exists()
