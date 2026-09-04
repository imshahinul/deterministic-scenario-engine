from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from decimal import Decimal
import json
import unittest

from scenario_engine.errors import ScenarioEngineError
from scenario_engine.ids import LogicalID
from scenario_engine.manifest import ENGINE_VERSION, ReplayCompatibilityError, ReproducibilityManifest
from scenario_engine.suite import (
    ArtifactReference,
    BatchItemResult,
    BatchManifest,
    BatchResultEnvelope,
    BatchStatus,
    BoundsMetadata,
    CompatibilityRecord,
    DomainPackRecord,
    ExecutionContext,
    ExecutionReplaySupport,
    FailureRecord,
    MatrixCase,
    MatrixCaseResultEnvelope,
    MatrixManifest,
    MatrixResultEnvelope,
    RunManifestEnvelope,
    SuiteContractError,
    SuiteManifest,
    SuiteSerializationError,
    UnsupportedReplayContractError,
    canonical_suite_bytes,
    parse_suite_bytes,
)
from scenario_engine.values import MISSING


HASH = "a" * 64
CLOCK = datetime(2026, 1, 1, tzinfo=timezone.utc)


def reference(kind: str, identity: str) -> ArtifactReference:
    return ArtifactReference(kind, identity, HASH)


def context() -> ExecutionContext:
    return ExecutionContext("seed", 3, "C", CLOCK)


def manifest() -> ReproducibilityManifest:
    return ReproducibilityManifest("seed", HASH, ENGINE_VERSION, 1, reference_clock_start=CLOCK, run_index=3)


class ModelTests(unittest.TestCase):
    def test_run_suite_and_compatibility_contracts(self):
        plugins = {"example.plugin": "1"}
        compatibility = CompatibilityRecord(
            "engine.v2", ExecutionReplaySupport.UNSUPPORTED, plugins,
            (DomainPackRecord("example.pack", "1", HASH),),
        )
        plugins["example.plugin"] = "changed"
        run = RunManifestEnvelope("checkout", context(), compatibility, child_manifest=manifest())
        self.assertIsNone(run.suite_hash)
        self.assertEqual(canonical_suite_bytes(parse_suite_bytes(canonical_suite_bytes(run))), canonical_suite_bytes(run))
        self.assertIs(
            parse_suite_bytes(canonical_suite_bytes(run)).compatibility.execution_replay,
            ExecutionReplaySupport.UNSUPPORTED,
        )
        self.assertEqual(compatibility.plugin_versions["example.plugin"], "1")
        with self.assertRaises(UnsupportedReplayContractError) as caught:
            compatibility.require_execution_replay()
        self.assertEqual(caught.exception.code, "replay.engine_version_unsupported")
        self.assertIsInstance(caught.exception, ReplayCompatibilityError)
        self.assertIsInstance(caught.exception, ScenarioEngineError)

        modules = {"catalog": HASH}
        suite = SuiteManifest("checkout", None, None, modules, child_runs=(reference("run", "r1"),))
        modules["catalog"] = "b" * 64
        self.assertEqual(suite.module_hashes["catalog"], HASH)
        with self.assertRaises(TypeError):
            suite.module_hashes["x"] = HASH  # type: ignore[index]
        with self.assertRaises(FrozenInstanceError):
            suite.composed_hash = HASH  # type: ignore[misc]

    def test_matrix_models_represent_order_without_expansion(self):
        mutable = {"country": "US", "amount": Decimal("10.50"), "nested": [MISSING, None, True, 1]}
        case = MatrixCase(4, "case-4", mutable, "replay-4")
        mutable["nested"].append(2)
        child = MatrixCaseResultEnvelope(case, reference("manifest", "m4"), reference("result", "r4"))
        model = MatrixManifest("checkout", HASH, context(), BoundsMetadata(100, 1, 5), (child,))
        envelope = MatrixResultEnvelope(model, (reference("result", "r4"),))
        self.assertEqual(tuple(case.assignment), ("country", "amount", "nested"))
        self.assertEqual(case.assignment["nested"], (MISSING, None, True, 1))
        self.assertEqual(envelope.manifest.cases[0].case.case_index, 4)

    def test_batch_models_validate_status_and_counts_without_execution(self):
        success = BatchItemResult(
            "run-1", "child-1", BatchStatus.SUCCESS,
            reference("manifest", "m1"), reference("result", "r1"),
        )
        failure = BatchItemResult(
            "run-2", "child-2", BatchStatus.FAILURE,
            child_manifest=reference("manifest", "m2"), failure=FailureRecord("execution", "run.failed", "safe"),
        )
        not_run = BatchItemResult("run-3", "child-3", BatchStatus.NOT_RUN)
        model = BatchManifest("plan", HASH, "bundle", (success, failure, not_run), 1, 1, 1)
        self.assertEqual(BatchResultEnvelope(model).manifest.items, (success, failure, not_run))
        with self.assertRaises(SuiteContractError):
            BatchManifest("plan", HASH, "bundle", (success,), 0, 0, 0)
        with self.assertRaises(SuiteContractError):
            BatchItemResult("run", "child", "success")  # type: ignore[arg-type]

    def test_strict_canonical_round_trip_preserves_typed_semantics(self):
        case = MatrixCase(
            0, "case", {
                "missing": MISSING, "null": None, "boolean": True, "integer": 1,
                "decimal": Decimal("1.00"), "clock": CLOCK,
                "logical": LogicalID("12345678-1234-5678-9234-567812345678"),
            }, "replay",
        )
        encoded = canonical_suite_bytes(case)
        parsed = parse_suite_bytes(encoded)
        self.assertEqual(canonical_suite_bytes(parsed), encoded)
        self.assertIs(parsed.assignment["missing"], MISSING)
        self.assertIsNone(parsed.assignment["null"])
        self.assertIs(type(parsed.assignment["boolean"]), bool)
        self.assertIs(type(parsed.assignment["integer"]), int)
        self.assertEqual(parsed.assignment["decimal"], Decimal("1.00"))
        self.assertIsInstance(parsed.assignment["logical"], LogicalID)
        self.assertEqual(encoded, canonical_suite_bytes(case))

    def test_strict_parser_rejects_versions_fields_duplicates_and_bad_values(self):
        encoded = canonical_suite_bytes(SuiteManifest("root", None, None))
        raw = json.loads(encoded)
        raw["schema_version"] = "suite.manifest/2"
        with self.assertRaises(SuiteContractError):
            parse_suite_bytes(json.dumps(raw).encode())
        raw = json.loads(encoded)
        del raw["root_scenario_identity"]
        with self.assertRaises(SuiteSerializationError):
            parse_suite_bytes(json.dumps(raw).encode())
        raw = json.loads(encoded)
        raw["unknown"] = 1
        with self.assertRaises(SuiteSerializationError):
            parse_suite_bytes(json.dumps(raw).encode())
        with self.assertRaises(SuiteSerializationError):
            parse_suite_bytes(b'{"$model":"SuiteManifest","$model":"SuiteManifest"}')
        with self.assertRaises(SuiteSerializationError):
            parse_suite_bytes(b'{"$model":"MatrixCase","assignment":[],"case_id":"c","case_index":0,"replay_identity":"r","extra":{"$type":"decimal","value":"NaN"}}')

    def test_identity_hash_and_uniqueness_validation(self):
        with self.assertRaises(SuiteContractError):
            ArtifactReference("run", "", HASH)
        with self.assertRaises(SuiteContractError):
            ArtifactReference("run", "id", "BAD")
        duplicate = reference("run", "same")
        with self.assertRaises(SuiteContractError):
            SuiteManifest("root", None, None, child_runs=(duplicate, duplicate))
        with self.assertRaises(SuiteContractError):
            CompatibilityRecord(
                "contract", ExecutionReplaySupport.SUPPORTED,
                domain_packs=(DomainPackRecord("p", "1", HASH), DomainPackRecord("p", "2", HASH)),
            )


if __name__ == "__main__":
    unittest.main()
