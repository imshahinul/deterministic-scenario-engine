from __future__ import annotations

from dataclasses import FrozenInstanceError
import hashlib
import json
import os
import socket
import time
from unittest.mock import patch

import pytest

import scenario_engine
from scenario_engine.evidence import (
    EVIDENCE_BUNDLE_SCHEMA_VERSION,
    EVIDENCE_ENTRY_SCHEMA_VERSION,
    EVIDENCE_PROVENANCE_SCHEMA_VERSION,
    EVIDENCE_RELATIONSHIP_SCHEMA_VERSION,
    MAX_ARTIFACT_BYTES,
    MAX_BUNDLE_ENTRIES,
    MAX_BUNDLE_INDEX_BYTES,
    MAX_BUNDLE_PATH_DEPTH,
    EvidenceBoundError,
    EvidenceBundle,
    EvidenceContractError,
    EvidenceEntry,
    EvidenceProvenance,
    EvidenceRelationship,
    EvidenceType,
    canonical_evidence_bytes,
    canonical_evidence_text,
    evidence_bundle_hash,
)


ZERO_HASH = "0" * 64
ONE_HASH = "1" * 64
FROZEN_ROOT_EXPORTS = (
    "ENGINE_VERSION", "MISSING", "LogicalID", "ExecutionAddress",
    "ScenarioResult", "ReproducibilityManifest", "parse_yaml",
    "parse_yaml_file", "compile_document", "run_scenario", "replay_scenario",
    "evaluate_scenario", "canonical_scenario_payload", "canonical_scenario_bytes",
    "canonical_scenario_hash", "GeneratorPlugin", "PluginRegistry",
    "PluginGenerationContext", "ScenarioEngineError", "DSLError",
    "DSLParseError", "DSLSchemaError", "DSLCompilationError",
    "ExpressionEvaluationError", "ResourceError", "ResourceValidationError",
    "ConstraintError", "ControlFlowError", "InvariantError", "FaultError",
    "OracleError", "ReplayCompatibilityError", "PluginError",
)


def entry(
    logical_id: str = "result:primary",
    *,
    path: str = "results/primary.json",
    sha256: str = ZERO_HASH,
    size_bytes: int = 2,
    provenance: EvidenceProvenance | None = None,
    schema_version: str = EVIDENCE_ENTRY_SCHEMA_VERSION,
) -> EvidenceEntry:
    return EvidenceEntry(
        logical_id=logical_id,
        evidence_type=EvidenceType.RESULT,
        artifact_schema="suite.run/1",
        media_type="application/json",
        path=path,
        sha256=sha256,
        size_bytes=size_bytes,
        provenance=provenance,
        schema_version=schema_version,
    )


def test_minimal_bundle_has_explicit_independent_versions_and_identity() -> None:
    bundle = EvidenceBundle(entries=())

    assert bundle.schema_version == "evidence.bundle/1" == EVIDENCE_BUNDLE_SCHEMA_VERSION
    assert EVIDENCE_ENTRY_SCHEMA_VERSION == "evidence.entry/1"
    assert EVIDENCE_RELATIONSHIP_SCHEMA_VERSION == "evidence.relationship/1"
    assert EVIDENCE_PROVENANCE_SCHEMA_VERSION == "evidence.provenance/1"
    assert bundle.bundle_id == evidence_bundle_hash(bundle)
    assert len(bundle.bundle_id) == 64


def test_representative_bundle_is_immutable_sorted_and_explicitly_linked() -> None:
    provenance = EvidenceProvenance(
        source_sha256=ONE_HASH,
        contract="evidence.export/1",
    )
    relationship = EvidenceRelationship(
        source_id="result:z", target_id="manifest:a", kind="described-by"
    )
    bundle = EvidenceBundle(
        entries=(
            entry("result:z", path="results/z.json", provenance=provenance),
            EvidenceEntry(
                logical_id="manifest:a",
                evidence_type=EvidenceType.MANIFEST,
                artifact_schema="suite.manifest/1",
                media_type="application/json",
                path="manifests/a.json",
                sha256=ONE_HASH,
                size_bytes=17,
            ),
        ),
        relationships=(relationship,),
    )

    assert tuple(item.logical_id for item in bundle.entries) == ("manifest:a", "result:z")
    assert bundle.relationships == (relationship,)
    with pytest.raises(FrozenInstanceError):
        bundle.entries = ()  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        bundle.entries[0].path = "other.json"  # type: ignore[misc]


def test_canonical_vector_is_deliberate_compact_utf8_json_without_newline() -> None:
    bundle = EvidenceBundle(entries=(entry(),))
    expected = (
        b'{"entries":[{"artifact_schema":"suite.run/1","evidence_type":"result",'
        b'"logical_id":"result:primary","media_type":"application/json",'
        b'"path":"results/primary.json","provenance":null,"schema_version":'
        b'"evidence.entry/1","sha256":"0000000000000000000000000000000000000000000000000000000000000000",'
        b'"size_bytes":2}],"relationships":[],"schema_version":"evidence.bundle/1"}'
    )

    assert canonical_evidence_bytes(bundle) == expected
    assert canonical_evidence_text(bundle).encode("utf-8") == expected
    assert not expected.endswith(b"\n")
    assert bundle.bundle_id == hashlib.sha256(expected).hexdigest()


def test_equivalent_input_order_cannot_change_canonical_bytes_or_hash() -> None:
    first = entry("result:a", path="results/a.json", sha256=ZERO_HASH)
    second = entry("result:b", path="results/b.json", sha256=ONE_HASH)
    rel_a = EvidenceRelationship("result:b", "result:a", "derived-from")
    rel_b = EvidenceRelationship("result:a", "result:b", "describes")
    one = EvidenceBundle((second, first), (rel_a, rel_b))
    two = EvidenceBundle((first, second), (rel_b, rel_a))

    assert canonical_evidence_bytes(one) == canonical_evidence_bytes(two)
    assert canonical_evidence_bytes(one) == canonical_evidence_bytes(one)
    assert evidence_bundle_hash(one) == evidence_bundle_hash(two) == one.bundle_id
    assert json.loads(canonical_evidence_text(one))["entries"][0]["logical_id"] == "result:a"


@pytest.mark.parametrize("value", ["", " space", "é", "?bad", "a" * 257])
def test_malformed_logical_identifiers_are_rejected(value: str) -> None:
    with pytest.raises(EvidenceContractError, match="logical_id"):
        entry(value)


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (lambda: EvidenceBundle((), schema_version="evidence.bundle/2"), "bundle"),
        (lambda: entry(schema_version="evidence.entry/2"), "entry"),
        (
            lambda: EvidenceRelationship("result:a", "result:b", "links", "evidence.relationship/2"),
            "relationship",
        ),
        (
            lambda: EvidenceProvenance(ZERO_HASH, "evidence.export/1", "evidence.provenance/2"),
            "provenance",
        ),
    ],
)
def test_unsupported_contract_versions_fail_closed(factory: object, message: str) -> None:
    with pytest.raises(EvidenceContractError, match=message):
        factory()  # type: ignore[operator]


def test_duplicate_logical_ids_paths_and_casefold_paths_are_rejected() -> None:
    with pytest.raises(EvidenceContractError, match="duplicate logical_id"):
        EvidenceBundle((entry(), entry(path="other.json")))
    with pytest.raises(EvidenceContractError, match="duplicate path"):
        EvidenceBundle((entry("result:a"), entry("result:b")))
    with pytest.raises(EvidenceContractError, match="case-fold"):
        EvidenceBundle((
            entry("result:a", path="Results/a.json"),
            entry("result:b", path="results/A.JSON"),
        ))


@pytest.mark.parametrize("value", ["", "A" * 64, "0" * 63, "g" * 64, 0])
def test_invalid_hashes_are_rejected(value: object) -> None:
    with pytest.raises(EvidenceContractError, match="SHA-256"):
        entry(sha256=value)  # type: ignore[arg-type]


def test_invalid_relationships_are_rejected_deterministically() -> None:
    a = entry("result:a", path="results/a.json")
    b = entry("result:b", path="results/b.json")
    with pytest.raises(EvidenceContractError, match="must differ"):
        EvidenceRelationship("result:a", "result:a", "derived-from")
    unknown = EvidenceRelationship("result:a", "result:c", "derived-from")
    with pytest.raises(EvidenceContractError, match="unknown logical_id"):
        EvidenceBundle((a, b), (unknown,))
    duplicate = EvidenceRelationship("result:a", "result:b", "derived-from")
    with pytest.raises(EvidenceContractError, match="duplicate relationship"):
        EvidenceBundle((a, b), (duplicate, duplicate))


@pytest.mark.parametrize(
    "path",
    ["", "/abs.json", "//server/share", "C:/x.json", "a\\b.json", "a//b", "./a", "a/../b", "https://host/x", "a\x00b"],
)
def test_unsafe_relative_path_values_are_rejected(path: str) -> None:
    with pytest.raises(EvidenceContractError, match="path"):
        entry(path=path)


def test_intrinsic_size_count_depth_and_index_bounds() -> None:
    for invalid in (-1, True, 1.5):
        with pytest.raises(EvidenceContractError, match="size_bytes"):
            entry(size_bytes=invalid)  # type: ignore[arg-type]
    with pytest.raises(EvidenceBoundError, match="artifact ceiling"):
        entry(size_bytes=MAX_ARTIFACT_BYTES + 1)
    with pytest.raises(EvidenceBoundError, match="depth ceiling"):
        entry(path="/".join(["a"] * (MAX_BUNDLE_PATH_DEPTH + 1)))

    one = entry()
    # Exercise the declared count precedence without allocating 100,001 models.
    with patch("scenario_engine.evidence.models.MAX_BUNDLE_ENTRIES", 0):
        with pytest.raises(EvidenceBoundError, match="entry ceiling"):
            EvidenceBundle((one,))
    with patch("scenario_engine.evidence.models.MAX_BUNDLE_INDEX_BYTES", 1):
        with pytest.raises(EvidenceBoundError, match="canonical index"):
            EvidenceBundle(())


def test_extra_fields_are_rejected_by_explicit_constructors() -> None:
    with pytest.raises(TypeError, match="unexpected keyword"):
        EvidenceBundle(entries=(), speculative=True)  # type: ignore[call-arg]


def test_construction_and_canonicalization_have_no_ambient_authority() -> None:
    original_environ = dict(os.environ)
    with (
        patch.object(time, "time", side_effect=AssertionError("clock accessed")),
        patch("random.random", side_effect=AssertionError("randomness accessed")),
        patch.object(socket, "create_connection", side_effect=AssertionError("network accessed")),
        patch("builtins.__import__", wraps=__import__) as importer,
    ):
        bundle = EvidenceBundle((entry(),))
        assert canonical_evidence_bytes(bundle)
    assert dict(os.environ) == original_environ
    assert not any(call.args and str(call.args[0]).startswith("provider") for call in importer.mock_calls)


def test_phase2_root_api_and_version_roles_remain_frozen() -> None:
    from scenario_engine._version import ENGINE_VERSION, VERSION
    from scenario_engine.suite import RUN_SCHEMA_VERSION, SUITE_SCHEMA_VERSION

    assert tuple(scenario_engine.__all__) == FROZEN_ROOT_EXPORTS
    assert VERSION == "2.1.1"
    assert ENGINE_VERSION == "1.0.0"
    assert RUN_SCHEMA_VERSION == "suite.run/1"
    assert SUITE_SCHEMA_VERSION == "suite.manifest/1"
