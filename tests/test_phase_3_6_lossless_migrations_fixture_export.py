from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from scenario_engine.evidence import (
    FIXTURE_INDEX_FILENAME,
    ArtifactDescriptor,
    EvidenceContractError,
    EvidenceDestinationError,
    EvidenceExportBoundError,
    EvidenceMigrationContractError,
    EvidenceMigrationSourceIntegrityError,
    FixtureDeclaration,
    canonical_fixture_index_bytes,
    canonical_migration_result_bytes,
    execute_lossless_migration,
    export_fixture_directory,
    plan_migration,
    read_evidence_bundle,
)


ROUTES = (
    ("result", "scenario.result/1", "1.0.0", "wrap-v1-result-as-evidence/1"),
    ("manifest", "scenario.manifest/1", "1.0.0", "wrap-v1-manifest-as-evidence/1"),
    ("suite", "suite.manifest/1", "2.0.0", "wrap-v2-suite-as-evidence/1"),
    ("composition", "composition.modules/1", "2.0.0", "wrap-v2-composition-as-evidence/1"),
    ("matrix", "suite.matrix/1", "2.0.0", "wrap-v2-matrix-as-evidence/1"),
    ("batch", "suite.batch/1", "2.0.0", "wrap-v2-batch-as-evidence/1"),
)


@pytest.mark.parametrize(("kind", "contract", "version", "transformation"), ROUTES)
def test_every_frozen_route_executes_losslessly_and_idempotently(
    tmp_path: Path, kind: str, contract: str, version: str, transformation: str,
) -> None:
    source_bytes = b'{"unknown":{"preserved":true},"z":1}'
    source = tmp_path / "source.json"
    source.write_bytes(source_bytes)
    digest = hashlib.sha256(source_bytes).hexdigest()
    descriptor = ArtifactDescriptor(kind, contract, version, digest)
    plan = plan_migration(descriptor)
    before = source.read_bytes()
    first = execute_lossless_migration(
        plan, source_descriptor=descriptor, source_path=source, destination=tmp_path / "one",
    )
    second = execute_lossless_migration(
        plan, source_descriptor=descriptor, source_path=source, destination=tmp_path / "two",
    )
    assert source.read_bytes() == before
    assert first == second
    assert canonical_migration_result_bytes(first) == canonical_migration_result_bytes(second)
    assert first.transformations == (transformation,)
    assert first.source_sha256 == digest and first.lossless is True
    one = read_evidence_bundle(tmp_path / "one" / "bundle.json", bundle_root=tmp_path / "one")
    assert one.entries[0].provenance.source_sha256 == digest
    assert one.entries[0].provenance.contract == transformation
    assert (tmp_path / "one" / one.entries[0].path).read_bytes() == source_bytes
    assert _tree(tmp_path / "one") == _tree(tmp_path / "two")


def test_migration_rejects_unsupported_mismatch_unknown_and_integrity_without_output(tmp_path: Path) -> None:
    source = tmp_path / "source.json"
    source.write_bytes(b"{}")
    unsupported_descriptor = ArtifactDescriptor("domain-pack", "domain-pack/1", "2.0.0")
    destination = tmp_path / "unsupported"
    with pytest.raises(EvidenceMigrationContractError, match="planned"):
        execute_lossless_migration(plan_migration(unsupported_descriptor), source_descriptor=unsupported_descriptor,
                                   source_path=source, destination=destination)
    assert not destination.exists()

    descriptor = ArtifactDescriptor("suite", "suite.manifest/1", "2.0.0", "a" * 64)
    with pytest.raises(EvidenceMigrationSourceIntegrityError, match="SHA-256"):
        execute_lossless_migration(plan_migration(descriptor), source_descriptor=descriptor,
                                   source_path=source, destination=tmp_path / "hash-mismatch")
    assert not (tmp_path / "hash-mismatch").exists()

    accepted = ArtifactDescriptor("suite", "suite.manifest/1", "2.0.0",
                                  hashlib.sha256(b"{}").hexdigest())
    wrong = ArtifactDescriptor("suite", "suite.manifest/1", "2.0.0")
    with pytest.raises(EvidenceMigrationContractError, match="does not match"):
        execute_lossless_migration(plan_migration(accepted), source_descriptor=wrong,
                                   source_path=source, destination=tmp_path / "wrong")


def test_fixture_zero_one_multiple_order_hashes_and_permutation_stability(tmp_path: Path) -> None:
    empty = export_fixture_directory((), destination=tmp_path / "empty")
    assert empty.entries == ()
    fixtures = (
        FixtureDeclaration("z-last", {"b": 2, "a": 1}),
        FixtureDeclaration("a-first", {"nested": {"z": 0, "a": True}}),
    )
    first = export_fixture_directory(fixtures, destination=tmp_path / "first")
    second = export_fixture_directory(tuple(reversed(fixtures)), destination=tmp_path / "second")
    assert [entry.fixture_id for entry in first.entries] == ["a-first", "z-last"]
    assert first == second
    assert canonical_fixture_index_bytes(first) == canonical_fixture_index_bytes(second)
    assert _tree(tmp_path / "first") == _tree(tmp_path / "second")
    payload = (tmp_path / "first" / "fixtures" / "z-last.json").read_bytes()
    assert payload == b'{"a":1,"b":2}'
    entry = first.entries[1]
    assert entry.size_bytes == len(payload)
    assert entry.sha256 == hashlib.sha256(payload).hexdigest()
    assert not (tmp_path / "first" / FIXTURE_INDEX_FILENAME).read_bytes().endswith(b"\n")


def test_fixture_rejects_duplicate_unsafe_existing_and_bounds_without_partial_output(tmp_path: Path) -> None:
    with pytest.raises(EvidenceContractError, match="portable safe"):
        FixtureDeclaration("../escape", {})
    duplicate = (FixtureDeclaration("same", {}), FixtureDeclaration("same", {"x": 1}))
    destination = tmp_path / "duplicate"
    with pytest.raises(EvidenceContractError, match="duplicate"):
        export_fixture_directory(duplicate, destination=destination)
    assert not destination.exists()
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(EvidenceDestinationError, match="already exists"):
        export_fixture_directory((), destination=existing)
    bounded = tmp_path / "bounded"
    with pytest.raises(EvidenceExportBoundError, match="aggregate"):
        export_fixture_directory((FixtureDeclaration("one", {"x": "long"}),),
                                 destination=bounded, max_aggregate_bytes=1)
    assert not bounded.exists()


def _tree(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes()
            for path in sorted(root.rglob("*")) if path.is_file()}
