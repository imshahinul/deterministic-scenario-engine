from __future__ import annotations

from dataclasses import FrozenInstanceError
import builtins
import importlib
import importlib.metadata
import json
import os
import random
import socket
import subprocess
import time
from unittest.mock import patch

import pytest

from scenario_engine.evidence import (
    CURRENT_PRODUCT_CONTRACT,
    EVIDENCE_COMPATIBILITY_REPORT_SCHEMA_VERSION,
    EVIDENCE_MIGRATION_PLAN_SCHEMA_VERSION,
    MAX_MIGRATION_STEPS,
    ArtifactDescriptor,
    CapabilityDisposition,
    CompatibilityCapability,
    CompatibilityReason,
    CompatibilityRequirement,
    EvidenceBoundError,
    EvidenceContractError,
    MigrationDisposition,
    MigrationPlan,
    MigrationStep,
    RequirementCoordinate,
    canonical_compatibility_report_bytes,
    canonical_migration_plan_bytes,
    compatibility_report,
    compatibility_report_hash,
    migration_plan_hash,
    plan_migration,
)


HASH = "a" * 64


def descriptor(kind: str, schema: str, product: str = "2.0.0", *, coordinates=(), source_hash=None):
    return ArtifactDescriptor(kind, schema, product, source_hash, tuple(coordinates))


def supported(report):
    return {item.capability for item in report.determinations
            if item.disposition is CapabilityDisposition.SUPPORTED}


def determination(report, capability):
    return next(item for item in report.determinations if item.capability is capability)


def matching(*requirements):
    expected = {
        CompatibilityRequirement.ENGINE_VERSION: "1.0.0",
        CompatibilityRequirement.DSL_VERSION: "1",
    }
    return tuple(RequirementCoordinate(item, expected.get(item, "required"), expected.get(item, "required"))
                 for item in requirements)


def test_vocabulary_contracts_immutability_and_validation() -> None:
    assert tuple(item.value for item in CompatibilityCapability) == (
        "READABLE", "INSPECTABLE", "DIFFABLE", "EXECUTABLE", "REPLAYABLE", "MIGRATABLE", "UNSUPPORTED",
    )
    assert EVIDENCE_COMPATIBILITY_REPORT_SCHEMA_VERSION == "evidence.compatibility-report/1"
    assert EVIDENCE_MIGRATION_PLAN_SCHEMA_VERSION == "evidence.migration-plan/1"
    assert CURRENT_PRODUCT_CONTRACT == "scenario-engine/2"
    value = descriptor("result", "scenario.result/1", source_hash=HASH)
    with pytest.raises(FrozenInstanceError):
        value.artifact_kind = "changed"  # type: ignore[misc]
    with pytest.raises(EvidenceContractError, match="lowercase SHA-256"):
        descriptor("result", "scenario.result/1", source_hash=HASH.upper())
    with pytest.raises(EvidenceContractError, match="duplicate requirement"):
        descriptor("result", "scenario.result/1", coordinates=(
            RequirementCoordinate(CompatibilityRequirement.DSL_VERSION, "1"),
            RequirementCoordinate(CompatibilityRequirement.DSL_VERSION, "1"),
        ))


@pytest.mark.parametrize(("source", "expected", "migratable"), (
    (descriptor("result", "scenario.result/1", "1.0.0"), {"READABLE", "INSPECTABLE", "DIFFABLE", "MIGRATABLE"}, True),
    (descriptor("manifest", "scenario.manifest/1", "1.0.0"), {"READABLE", "INSPECTABLE", "DIFFABLE", "MIGRATABLE"}, True),
    (descriptor("dsl", "scenario.dsl/1", "1.0.0"), {"READABLE", "INSPECTABLE", "DIFFABLE"}, False),
    (descriptor("result", "scenario.result/1"), {"READABLE", "INSPECTABLE", "DIFFABLE"}, False),
    (descriptor("manifest", "scenario.manifest/1"), {"READABLE", "INSPECTABLE", "DIFFABLE"}, False),
    (descriptor("suite", "suite.manifest/1"), {"READABLE", "INSPECTABLE", "DIFFABLE", "MIGRATABLE"}, True),
    (descriptor("composition", "composition.modules/1"), {"READABLE", "INSPECTABLE", "DIFFABLE", "MIGRATABLE"}, True),
    (descriptor("matrix", "suite.matrix/1"), {"READABLE", "INSPECTABLE", "DIFFABLE", "MIGRATABLE"}, True),
    (descriptor("batch", "suite.batch/1"), {"READABLE", "INSPECTABLE", "DIFFABLE", "MIGRATABLE"}, True),
    (descriptor("domain-pack", "domain-pack/1"), {"READABLE", "INSPECTABLE", "DIFFABLE"}, False),
    (descriptor("oracle-assertion", "oracle.assertion/1"), {"READABLE", "INSPECTABLE", "DIFFABLE"}, False),
    (descriptor("oracle-evaluation", "oracle.evaluation/1"), {"READABLE", "INSPECTABLE", "DIFFABLE"}, False),
    (descriptor("evidence-bundle", "evidence.bundle/1", "3.0.0"), {"READABLE", "INSPECTABLE", "DIFFABLE"}, False),
    (descriptor("evidence-adapter-capability", "evidence.adapter-capability/1", "3.0.0"), {"READABLE", "INSPECTABLE", "DIFFABLE"}, False),
    (descriptor("evidence-adapter-receipt", "evidence.adapter-receipt/1", "3.0.0"), {"READABLE", "INSPECTABLE", "DIFFABLE"}, False),
    (descriptor("evidence-compatibility-report", "evidence.compatibility-report/1", "3.0.0"), {"READABLE", "INSPECTABLE", "DIFFABLE"}, False),
    (descriptor("evidence-migration-plan", "evidence.migration-plan/1", "3.0.0"), {"READABLE", "INSPECTABLE", "DIFFABLE"}, False),
))
def test_full_frozen_capability_matrix(source, expected, migratable) -> None:
    report = compatibility_report(source)
    assert {item.value for item in supported(report)} == expected
    assert report.lossless_migration_known is migratable


def test_unknown_schema_and_future_version_fail_closed() -> None:
    for source, reason in (
        (descriptor("future", "future.artifact/1", "9.0.0"), CompatibilityReason.UNSUPPORTED_SCHEMA),
        (descriptor("result", "scenario.result/1", "9.0.0"), CompatibilityReason.UNKNOWN_VERSION),
        (descriptor("result", "scenario.result/2", "2.0.0"), CompatibilityReason.UNSUPPORTED_SCHEMA),
    ):
        report = compatibility_report(source)
        assert report.capabilities == (CompatibilityCapability.UNSUPPORTED,)
        assert all(item.disposition is CapabilityDisposition.UNSUPPORTED for item in report.determinations)
        assert determination(report, CompatibilityCapability.READABLE).reason is reason


def test_conditional_execution_and_replay_require_complete_matching_coordinates() -> None:
    names = (
        CompatibilityRequirement.ENGINE_VERSION, CompatibilityRequirement.DSL_VERSION,
        CompatibilityRequirement.SCENARIO_HASH, CompatibilityRequirement.SOURCE_BYTES,
    )
    absent = compatibility_report(descriptor("result", "scenario.result/1"))
    assert determination(absent, CompatibilityCapability.REPLAYABLE).reason is CompatibilityReason.MISSING_REQUIRED_COORDINATE
    mismatch = compatibility_report(descriptor("result", "scenario.result/1", coordinates=(
        RequirementCoordinate(CompatibilityRequirement.ENGINE_VERSION, "1.0.0", "9.0.0"),
        *matching(*names[1:]),
    )))
    assert determination(mismatch, CompatibilityCapability.REPLAYABLE).reason is CompatibilityReason.ENGINE_VERSION_MISMATCH
    complete = compatibility_report(descriptor("result", "scenario.result/1", coordinates=matching(*names)))
    assert {CompatibilityCapability.EXECUTABLE, CompatibilityCapability.REPLAYABLE} <= supported(complete)
    legacy = compatibility_report(descriptor("result", "scenario.result/1", "1.0.0", coordinates=matching(*names)))
    assert determination(legacy, CompatibilityCapability.REPLAYABLE).reason is CompatibilityReason.LEGACY_REPLAY_UNSUPPORTED


def test_dsl_matrix_domain_pack_batch_and_assertion_distinctions() -> None:
    dsl = compatibility_report(descriptor("dsl", "scenario.dsl/1", "1.0.0", coordinates=matching(
        CompatibilityRequirement.ENGINE_VERSION, CompatibilityRequirement.DSL_VERSION,
        CompatibilityRequirement.SCENARIO_HASH, CompatibilityRequirement.SOURCE_BYTES,
    )))
    assert {CompatibilityCapability.EXECUTABLE, CompatibilityCapability.REPLAYABLE} <= supported(dsl)
    matrix = compatibility_report(descriptor("matrix", "suite.matrix/1", coordinates=matching(
        CompatibilityRequirement.ENGINE_VERSION, CompatibilityRequirement.DSL_VERSION,
        CompatibilityRequirement.SCENARIO_HASH, CompatibilityRequirement.SOURCE_BYTES,
        CompatibilityRequirement.RESOURCE_HASHES, CompatibilityRequirement.COMPOSITION_CONTEXT,
    )))
    assert determination(matrix, CompatibilityCapability.REPLAYABLE).reason is CompatibilityReason.MISSING_REQUIRED_COORDINATE
    pack = compatibility_report(descriptor("domain-pack", "domain-pack/1", coordinates=matching(
        CompatibilityRequirement.DOMAIN_PACK_CONTEXT, CompatibilityRequirement.PLUGIN_CONTEXT,
    )))
    assert {CompatibilityCapability.EXECUTABLE, CompatibilityCapability.REPLAYABLE} <= supported(pack)
    batch = compatibility_report(descriptor("batch", "suite.batch/1"))
    assert determination(batch, CompatibilityCapability.EXECUTABLE).reason is CompatibilityReason.BATCH_RECORD_NOT_EXECUTION_STATE
    assertion = compatibility_report(descriptor("oracle-assertion", "oracle.assertion/1"))
    assert determination(assertion, CompatibilityCapability.EXECUTABLE).reason is CompatibilityReason.ASSERTION_EXECUTION_NOT_IMPLIED


def test_report_is_canonical_repeatable_permutation_stable_and_retains_hash() -> None:
    coordinates = matching(
        CompatibilityRequirement.DSL_VERSION, CompatibilityRequirement.ENGINE_VERSION,
        CompatibilityRequirement.SOURCE_BYTES, CompatibilityRequirement.SCENARIO_HASH,
    )
    first = compatibility_report(descriptor("result", "scenario.result/1", coordinates=coordinates, source_hash=HASH))
    second = compatibility_report(descriptor("result", "scenario.result/1", coordinates=reversed(coordinates), source_hash=HASH))
    assert first == second
    encoded = canonical_compatibility_report_bytes(first)
    assert encoded == canonical_compatibility_report_bytes(second)
    assert not encoded.endswith(b"\n") and json.loads(encoded)["source"]["source_sha256"] == HASH
    assert compatibility_report_hash(first) == compatibility_report_hash(second)
    assert [item["capability"] for item in json.loads(encoded)["determinations"]] == [
        "READABLE", "INSPECTABLE", "DIFFABLE", "EXECUTABLE", "REPLAYABLE", "MIGRATABLE",
    ]


def test_known_wrapper_plan_source_link_no_path_and_canonical_identity() -> None:
    source = descriptor("suite", "suite.manifest/1", source_hash=HASH)
    plan = plan_migration(source)
    assert plan.disposition is MigrationDisposition.PLANNED
    assert plan.source.source_sha256 == HASH
    assert plan.steps == (MigrationStep(
        "wrap-v2-suite-as-evidence/1", "suite.manifest/1", "evidence.bundle/1", True,
        ("preserve-source-bytes", "preserve-source-sha256"),
    ),)
    assert plan.plan_id == migration_plan_hash(plan)
    assert canonical_migration_plan_bytes(plan) == canonical_migration_plan_bytes(plan)
    assert b'"plan_id"' not in canonical_migration_plan_bytes(plan)
    assert plan_migration(descriptor("domain-pack", "domain-pack/1")).disposition is MigrationDisposition.UNSUPPORTED
    assert plan_migration(source, "future.target/1").reason is CompatibilityReason.NO_LOSSLESS_MIGRATION_PATH


def test_plan_validation_enforces_maximum_acyclic_contiguous_lossless_routes() -> None:
    source = descriptor("suite", "suite.manifest/1")
    step = MigrationStep("copy/1", "suite.manifest/1", "evidence.bundle/1", True)
    with pytest.raises(EvidenceBoundError, match=str(MAX_MIGRATION_STEPS)):
        MigrationPlan(source, "evidence.bundle/1", MigrationDisposition.PLANNED,
                      CompatibilityReason.SUPPORTED, (step,) * (MAX_MIGRATION_STEPS + 1))
    with pytest.raises(EvidenceContractError, match="acyclic"):
        MigrationPlan(source, "suite.manifest/1", MigrationDisposition.PLANNED,
                      CompatibilityReason.SUPPORTED, (MigrationStep(
                          "identity/1", "suite.manifest/1", "suite.manifest/1", True,
                      ),))
    with pytest.raises(EvidenceContractError, match="declared lossless"):
        MigrationStep("lossy/1", "suite.manifest/1", "evidence.bundle/1", False)


def test_reporting_and_planning_are_pure_and_do_not_mutate_or_use_ambient_authority() -> None:
    import scenario_engine.evidence.adapter as adapter_module

    source = descriptor("suite", "suite.manifest/1", source_hash=HASH)
    before = source
    environment = dict(os.environ)
    with (
        patch.object(builtins, "open", side_effect=AssertionError("filesystem accessed")),
        patch.object(os, "getenv", side_effect=AssertionError("environment accessed")),
        patch.object(time, "time", side_effect=AssertionError("clock accessed")),
        patch.object(random, "random", side_effect=AssertionError("random accessed")),
        patch.object(socket, "create_connection", side_effect=AssertionError("network accessed")),
        patch.object(socket.socket, "connect", side_effect=AssertionError("socket accessed")),
        patch.object(subprocess, "run", side_effect=AssertionError("subprocess accessed")),
        patch.object(importlib, "import_module", side_effect=AssertionError("dynamic import accessed")),
        patch.object(importlib.metadata, "entry_points", side_effect=AssertionError("discovery accessed")),
        patch.object(adapter_module, "publish_evidence_bundles", side_effect=AssertionError("adapter invoked")),
    ):
        report = compatibility_report(source)
        plan = plan_migration(source)
    assert report.lossless_migration_known and plan.disposition is MigrationDisposition.PLANNED
    assert source is before and source == before and dict(os.environ) == environment
