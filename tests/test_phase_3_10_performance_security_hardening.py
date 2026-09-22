"""Phase 3 evidence performance/security bounds and structural regression guards."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from time import perf_counter

import pytest

from scenario_engine.evidence import (
    DEFAULT_ADAPTER_IN_FLIGHT, DEFAULT_AGGREGATE_BUNDLE_BYTES,
    MAX_ADAPTER_IN_FLIGHT, MAX_ADAPTER_RECEIPT_BYTES, MAX_ADAPTER_RECEIPTS_BYTES,
    MAX_AGGREGATE_BUNDLE_BYTES, MAX_ARTIFACT_BYTES, MAX_BUNDLE_ENTRIES,
    MAX_BUNDLE_INDEX_BYTES, MAX_BUNDLE_INDEX_DEPTH, MAX_BUNDLE_PATH_DEPTH,
    MAX_JSONL_RECORDS, MAX_MIGRATION_STEPS, ArtifactDescriptor,
    EvidenceAdapterBoundError, EvidenceAdapterCapability, EvidenceAdapterPublication,
    EvidenceAdapterReceiptStatus, EvidenceBoundError, EvidenceBundle, EvidenceEntry,
    EvidenceExportBoundError, EvidenceFilesystemError, EvidenceIndexError,
    EvidenceIntegrityError, EvidenceType, EvidenceValidationBoundError,
    canonical_evidence_bytes, compatibility_report, plan_migration,
    publish_evidence_bundles, read_evidence_bundle, write_evidence_jsonl,
)


ZERO_HASH = "0" * 64
GUARDRAILS = {"bundle_10000": 5.0, "jsonl_25000": 5.0, "compatibility_6000": 5.0}


def _entry(index: int, *, path: str | None = None, size: int = 1) -> EvidenceEntry:
    return EvidenceEntry(
        f"result:{index:05d}", EvidenceType.RESULT, "suite.run/1", "application/json",
        path or f"artifacts/{index:05d}.json", hashlib.sha256(b"x" * size).hexdigest(), size,
    )


def _measure(name: str, operation):
    started = perf_counter()
    result = operation()
    seconds = perf_counter() - started
    print(f"PHASE3_10_METRIC name={name} seconds={seconds:.6f} guardrail={GUARDRAILS[name]:.3f}")
    assert seconds < GUARDRAILS[name]
    return result


def _write_bundle(root: Path, data: bytes = b"x") -> EvidenceBundle:
    (root / "artifacts").mkdir(parents=True)
    (root / "artifacts/00000.json").write_bytes(data)
    bundle = EvidenceBundle((_entry(0, size=len(data)),))
    (root / "bundle.json").write_bytes(canonical_evidence_bytes(bundle))
    return bundle


def test_frozen_phase3_bounds_are_exact_and_performance_guardrails_are_broad() -> None:
    assert (MAX_BUNDLE_ENTRIES, MAX_JSONL_RECORDS) == (100_000, 100_000)
    assert (MAX_BUNDLE_INDEX_BYTES, MAX_ARTIFACT_BYTES) == (16 << 20, 256 << 20)
    assert (DEFAULT_AGGREGATE_BUNDLE_BYTES, MAX_AGGREGATE_BUNDLE_BYTES) == (256 << 20, 4 << 30)
    assert (MAX_BUNDLE_PATH_DEPTH, MAX_BUNDLE_INDEX_DEPTH) == (64, 64)
    assert (DEFAULT_ADAPTER_IN_FLIGHT, MAX_ADAPTER_IN_FLIGHT) == (64, 1_024)
    assert (MAX_ADAPTER_RECEIPT_BYTES, MAX_ADAPTER_RECEIPTS_BYTES) == (1 << 20, 16 << 20)
    assert MAX_MIGRATION_STEPS == 1_000

    bundle = _measure("bundle_10000", lambda: EvidenceBundle(tuple(_entry(i) for i in range(10_000))))
    assert bundle.bundle_id == hashlib.sha256(canonical_evidence_bytes(bundle)).hexdigest()
    sink = io.BytesIO()
    _measure("jsonl_25000", lambda: write_evidence_jsonl(({"ordinal": i} for i in range(25_000)), sink))
    descriptors = (
        ArtifactDescriptor("result", "scenario.result/1", "1.0.0", ZERO_HASH),
        ArtifactDescriptor("suite", "suite.manifest/1", "2.0.0", ZERO_HASH),
        ArtifactDescriptor("future", "future/99", "99.0.0", ZERO_HASH),
    )
    results = _measure(
        "compatibility_6000",
        lambda: [(compatibility_report(item), plan_migration(item)) for _ in range(2_000) for item in descriptors],
    )
    assert len(results) == 6_000


def test_exact_and_one_over_model_jsonl_and_adapter_bounds(monkeypatch) -> None:
    import scenario_engine.evidence.models as models
    import scenario_engine.evidence.export as exporter

    monkeypatch.setattr(models, "MAX_BUNDLE_ENTRIES", 2)
    assert len(EvidenceBundle((_entry(0), _entry(1))).entries) == 2
    with pytest.raises(EvidenceBoundError):
        EvidenceBundle((_entry(0), _entry(1), _entry(2)))

    monkeypatch.setattr(exporter, "MAX_JSONL_RECORDS", 2)
    assert write_evidence_jsonl(iter((1, 2)), io.BytesIO())
    consumed = 0
    def records():
        nonlocal consumed
        for value in range(10):
            consumed += 1
            yield value
    with pytest.raises(EvidenceExportBoundError):
        write_evidence_jsonl(records(), io.BytesIO())
    assert consumed == 3

    class Adapter:
        capability = EvidenceAdapterCapability("fake", "1")
        def publish_bundle(self, bundle):
            return EvidenceAdapterPublication("fake://ok")
    with pytest.raises(EvidenceAdapterBoundError):
        publish_evidence_bundles(Adapter(), (), max_in_flight=MAX_ADAPTER_IN_FLIGHT + 1)
    with pytest.raises(EvidenceAdapterBoundError):
        publish_evidence_bundles(Adapter(), (), workers=2, max_in_flight=1)


def test_reader_rejects_oversized_malformed_deep_noncanonical_and_unsafe_files(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "bundle"
    root.mkdir()
    index = root / "bundle.json"

    import scenario_engine.evidence.read as reader
    monkeypatch.setattr(reader, "MAX_BUNDLE_INDEX_BYTES", 8)
    index.write_bytes(b"{" + b"x" * 8)
    requests: list[int] = []
    original_read = reader.os.read
    def observed(fd: int, size: int) -> bytes:
        requests.append(size)
        return original_read(fd, size)
    monkeypatch.setattr(reader.os, "read", observed)
    with pytest.raises(EvidenceValidationBoundError):
        read_evidence_bundle(index, bundle_root=root)
    assert max(requests) <= 9

    monkeypatch.undo()
    for payload in (b"\xff", b"[]", b'{"entries":[], "relationships":[],"schema_version":"evidence.bundle/1"}'):
        index.write_bytes(payload)
        with pytest.raises(EvidenceIndexError):
            read_evidence_bundle(index, bundle_root=root)

    nested: object = 0
    for _ in range(MAX_BUNDLE_INDEX_DEPTH + 2):
        nested = [nested]
    index.write_text(json.dumps(nested, separators=(",", ":")), encoding="utf-8")
    with pytest.raises(EvidenceValidationBoundError):
        read_evidence_bundle(index, bundle_root=root)

    target = tmp_path / "target.json"
    target.write_bytes(canonical_evidence_bytes(EvidenceBundle(())))
    index.unlink()
    index.symlink_to(target)
    with pytest.raises(EvidenceFilesystemError):
        read_evidence_bundle(index, bundle_root=root)


def test_reader_streams_artifacts_and_rejects_symlink_directory_hash_and_aggregate(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "valid"
    bundle = _write_bundle(root, b"x" * (3 * 65536 + 7))
    import scenario_engine.evidence.read as reader
    requests: list[int] = []
    original = reader.os.read
    def observed(fd: int, size: int) -> bytes:
        requests.append(size)
        return original(fd, size)
    monkeypatch.setattr(reader.os, "read", observed)
    assert read_evidence_bundle(root / "bundle.json", bundle_root=root) == bundle
    assert max(requests) <= 65536

    with pytest.raises(EvidenceValidationBoundError):
        read_evidence_bundle(root / "bundle.json", bundle_root=root, max_aggregate_bytes=bundle.entries[0].size_bytes - 1)
    (root / "artifacts/00000.json").write_bytes(b"tampered")
    with pytest.raises(EvidenceIntegrityError):
        read_evidence_bundle(root / "bundle.json", bundle_root=root)

    unsafe = tmp_path / "unsafe"
    unsafe.mkdir()
    (unsafe / "bundle.json").write_bytes(canonical_evidence_bytes(bundle))
    (unsafe / "artifacts").symlink_to(root / "artifacts", target_is_directory=True)
    with pytest.raises(EvidenceFilesystemError):
        read_evidence_bundle(unsafe / "bundle.json", bundle_root=unsafe)

    directory = tmp_path / "directory"
    directory.mkdir()
    (directory / "artifacts/00000.json").mkdir(parents=True)
    (directory / "bundle.json").write_bytes(canonical_evidence_bytes(bundle))
    with pytest.raises(EvidenceFilesystemError):
        read_evidence_bundle(directory / "bundle.json", bundle_root=directory)


def test_adapter_window_is_ordered_bounded_and_redacts_provider_exception() -> None:
    empty = EvidenceBundle(())
    class RedactingAdapter:
        capability = EvidenceAdapterCapability("fake", "1")
        def publish_bundle(self, bundle):
            raise RuntimeError("credential=secret-token")
    receipts = publish_evidence_bundles(RedactingAdapter(), (empty for _ in range(20)), workers=4, max_in_flight=8)
    assert tuple(item.ordinal for item in receipts) == tuple(range(20))
    assert all(item.status is EvidenceAdapterReceiptStatus.FAILURE for item in receipts)
    assert all(item.error_code == "adapter.operation_failed" for item in receipts)
    assert "secret-token" not in repr(receipts)
    with pytest.raises(EvidenceAdapterBoundError):
        publish_evidence_bundles(RedactingAdapter(), (empty,), max_receipts_bytes=1)


def test_canonical_identity_excludes_runtime_authority_and_incidental_values() -> None:
    first = EvidenceBundle((_entry(1), _entry(0)))
    second = EvidenceBundle((_entry(0), _entry(1)))
    assert canonical_evidence_bytes(first) == canonical_evidence_bytes(second)
    forbidden = (b"perf_counter", b"seconds", b"pid", b"environ", b"0x")
    assert all(value not in canonical_evidence_bytes(first) for value in forbidden)
    for value in (MAX_AGGREGATE_BUNDLE_BYTES + 1, True, -1):
        with pytest.raises(EvidenceValidationBoundError):
            read_evidence_bundle(Path("/not-used"), bundle_root=Path("/not-used"), max_aggregate_bytes=value)
