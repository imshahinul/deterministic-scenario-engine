from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from scenario_engine.compatibility import CompatibilityClassification, classify_engine_contract
from scenario_engine.dsl import UnsupportedDSL2ExecutionError, compile_document, parse_yaml, run_scenario
from scenario_engine.dsl.actor_runtime import execute_actors_internal
from scenario_engine.engine2 import (
    Engine2EvidenceBoundError, Engine2EvidenceError, Engine2ReplayMismatch,
    MAX_CANONICAL_RESULT_BYTES, MANIFEST2_CONTRACT, RESULT2_CONTRACT,
    SUITE_RUN2_CONTRACT, SuiteRun2, SuiteRun2Member, canonical_manifest2_identity_bytes,
    canonical_result2_bytes, canonical_result2_identity_bytes, canonical_suite_run2_bytes,
    construct_result2, exact_replay_result2_internal, read_manifest2, read_result2,
    read_suite_run2,
)
from scenario_engine.invariants import InvariantViolation
from scenario_engine.schedule import canonical_schedule_bytes


ROOT = Path(__file__).parents[1]
WRITE = "      - id: write\n        write: {value: {$add: [{$state: value}, {$literal: 1}]}}\n        advance: {seconds: 1}\n        transition: null\n"
READ = "      - id: read\n        write: {observed: {$state: value}}\n        transition: null\n"


def actor(name: str, steps: str) -> str:
    return f"  - id: {name}\n    steps:\n{steps}"


def scenario(extra: str = ""):
    raw = ("dsl_version: 2\nscenario: result-case\nclock: {start: '2026-01-01T00:00:00Z'}\n"
           "initial_state: {value: 0, observed: -1}\nactors:\n" +
           actor("reader", READ) + actor("writer", WRITE) + extra)
    return compile_document(parse_yaml(raw)), raw


def produced(root="root", schedule_seed=7):
    compiled, _ = scenario()
    outcome = execute_actors_internal(compiled, root, schedule_seed)
    return compiled, outcome, construct_result2(compiled, outcome)


def rehash(payload: dict) -> bytes:
    payload.pop("result_hash", None)
    payload["result_hash"] = hashlib.sha256(json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def test_t01_t12_manifest_result_identity_linkage_and_observations() -> None:
    compiled, outcome, result = produced()
    assert result.contract == RESULT2_CONTRACT and result.manifest.contract == MANIFEST2_CONTRACT
    assert result.manifest.engine_version == "2.0.0" and result.manifest.dsl_version == 2
    assert result.manifest.root_seed == "root" and result.manifest.schedule_seed == 7
    assert result.manifest.manifest_hash == hashlib.sha256(canonical_manifest2_identity_bytes(result.manifest)).hexdigest()
    assert result.result_hash == hashlib.sha256(canonical_result2_identity_bytes(result)).hexdigest()
    assert result.schedule_reference.schedule_hash == outcome.schedule.schedule_hash
    assert [item["actor"] for item in result.history] == [
        record.address.semantic().split("/step/", 1)[0] for record in outcome.committed_history
    ]
    assert result.final_state == outcome.final_state
    assert result.final_logical_clock == outcome.final_logical_clock
    assert tuple(item["terminal"] for item in result.actors) == (True, True)
    assert canonical_result2_bytes(result) == canonical_result2_bytes(construct_result2(compiled, outcome))
    assert read_result2(canonical_result2_bytes(result)) == result
    assert read_manifest2(__import__("scenario_engine.engine2", fromlist=["canonical_manifest2_bytes"])
                          .canonical_manifest2_bytes(result.manifest)) == result.manifest


def test_t03_generation_and_schedule_seeds_are_independent() -> None:
    _, _, first = produced("same", 1)
    _, _, second = produced("same", 2)
    assert first.manifest.root_seed == second.manifest.root_seed
    assert first.manifest.schedule_seed != second.manifest.schedule_seed
    assert first.manifest.manifest_hash != second.manifest.manifest_hash


def test_t13_t14_failure_is_deterministic_and_success_is_not_fabricated() -> None:
    compiled, _ = scenario("invariants:\n  - id: bounded\n    check: {$lte: [{$state: value}, {$literal: 0}]}\n")
    for seed in range(50):
        try:
            execute_actors_internal(compiled, "root", seed)
        except InvariantViolation as error:
            result = construct_result2(compiled, error.internal_outcome)
            assert result.classification == "FAILED" and result.failure is not None
            assert result.failure.code == "InvariantViolation"
            with pytest.raises(Engine2EvidenceError): replace(
                result, classification="SUCCESS", result_hash="",
            )
            return
    pytest.fail("no bounded seed selected the failing actor")


def test_t15_t17_suite_schema_order_and_child_contracts() -> None:
    _, outcome, result = produced()
    one = SuiteRun2Member(result.result_hash, result.manifest.manifest_hash, outcome.schedule.schedule_hash)
    two = SuiteRun2Member("f" * 64, "e" * 64, "d" * 64)
    suite = SuiteRun2((two, one))
    assert suite.contract == SUITE_RUN2_CONTRACT
    assert suite.members == tuple(sorted((one, two), key=lambda x: (x.result_hash, x.manifest_hash, x.schedule_hash)))
    assert read_suite_run2(canonical_suite_run2_bytes(suite)) == suite
    with pytest.raises(Engine2EvidenceError): replace(one, result_contract="scenario.result/1")


def test_t18_t21_explicit_dispatch_and_cross_version_rejection() -> None:
    classify = lambda d, e, r, op="replay": classify_engine_contract(
        dsl_version=d, engine_version=e, result_contract=r, operation=op,
    ).classification
    assert classify(1, "1.0.0", "scenario.result/1") is CompatibilityClassification.SUPPORTED_EXACT
    assert classify(2, "2.0.0", "scenario.result/2") is CompatibilityClassification.SUPPORTED_EXACT
    assert classify(1, "1.0.0", "scenario.result/2") is CompatibilityClassification.UNSUPPORTED_CROSS_MAJOR
    assert classify(2, "9.0.0", "scenario.result/2") is CompatibilityClassification.UNKNOWN_VERSION
    assert classify(1, "2.0.0", "scenario.result/1", "inspect") is CompatibilityClassification.SUPPORTED_LEGACY_OPERATION
    assert classify(1, "2.0.0", "scenario.result/1") is CompatibilityClassification.UNSUPPORTED_CROSS_MAJOR


def test_t22_t25_strict_reader_missing_unknown_duplicate_and_wrong_type() -> None:
    _, _, result = produced()
    encoded = canonical_result2_bytes(result)
    payload = json.loads(encoded)
    payload.pop("actors")
    with pytest.raises(Engine2EvidenceError): read_result2(json.dumps(payload).encode())
    payload = json.loads(encoded); payload["unknown"] = 1
    with pytest.raises(Engine2EvidenceError): read_result2(json.dumps(payload).encode())
    with pytest.raises(Engine2EvidenceError, match="duplicate"):
        read_result2(encoded.replace(b'{"actors":', b'{"actors":[],"actors":', 1))
    payload = json.loads(encoded); payload["manifest"]["run_index"] = True
    with pytest.raises(Engine2EvidenceError): read_result2(rehash(payload))


@pytest.mark.parametrize("field", ["scenario_hash", "input_resource_hashes", "root_seed", "schedule_seed",
                                    "scheduler_contract", "run_index", "schedule_hash"])
def test_t26_t31_manifest_schedule_mismatches_fail(field: str) -> None:
    compiled, outcome, result = produced()
    with pytest.raises((Engine2ReplayMismatch, Engine2EvidenceError)):
        if field == "schedule_hash":
            altered = replace(result, schedule_reference=replace(result.schedule_reference, schedule_hash="f" * 64),
                              result_hash="")
        else:
            changes = {field: ({"x": "f" * 64} if field == "input_resource_hashes" else
                               "f" * 64 if field == "scenario_hash" else "different" if field == "root_seed" else
                               "scenario.scheduler/999" if field == "scheduler_contract" else 8)}
            if field == "scenario_hash":
                altered = replace(result, manifest=replace(result.manifest, **changes, manifest_hash=""),
                                  schedule_reference=replace(result.schedule_reference, scenario_hash="f" * 64),
                                  result_hash="")
            else:
                altered = replace(result, manifest=replace(result.manifest, **changes, manifest_hash=""),
                                  result_hash="")
        exact_replay_result2_internal(altered, outcome.schedule, compiled)


@pytest.mark.parametrize("field", ["result_hash", "history", "final_state", "final_logical_clock", "actors"])
def test_t32_t36_corruption_and_observation_modification_fail(field: str) -> None:
    compiled, outcome, result = produced()
    if field == "result_hash":
        data = canonical_result2_bytes(result).replace(result.result_hash.encode(), b"0" * 64)
        with pytest.raises(Engine2EvidenceError): read_result2(data)
        return
    changes = {"history": result.history[:-1], "final_state": {"value": 999},
               "final_logical_clock": result.manifest.reference_clock_start,
               "actors": tuple({**dict(result.actors[0]), "terminal": False} for _ in (0,)) + result.actors[1:]}
    altered = replace(result, **{field: changes[field]}, result_hash="")
    with pytest.raises(Engine2ReplayMismatch): exact_replay_result2_internal(altered, outcome.schedule, compiled)


def test_t37_t40_exact_replay_schedule_verifier_and_historical_policy(monkeypatch) -> None:
    import scenario_engine.engine2 as module
    compiled, outcome, result = produced()
    called = []
    original = module.exact_replay_internal
    monkeypatch.setattr(module, "exact_replay_internal", lambda *a, **k: (called.append(True), original(*a, **k))[1])
    replay = exact_replay_result2_internal(result, outcome.schedule, compiled)
    assert called == [True] and replay.final_state == outcome.final_state


def test_t41_t47_immutable_bounded_redacted_and_cross_process_deterministic(monkeypatch) -> None:
    import scenario_engine.engine2 as module
    _, _, result = produced()
    with pytest.raises(FrozenInstanceError): result.classification = "FAILED"  # type: ignore[misc]
    with pytest.raises(TypeError): result.final_state["value"] = 9  # type: ignore[index]
    assert b"/Users/" not in canonical_result2_bytes(result)
    hostile = canonical_result2_bytes(result).replace(result.manifest.scenario_hash.encode(), b"/tmp/secret")
    with pytest.raises(Engine2EvidenceError) as error: read_result2(hostile)
    assert "/tmp/secret" not in str(error.value)
    monkeypatch.setattr(module, "MAX_CANONICAL_RESULT_BYTES", 1)
    with pytest.raises(Engine2EvidenceBoundError): canonical_result2_bytes(result)
    _, raw = scenario()
    code = f'''from scenario_engine.dsl import parse_yaml,compile_document\nfrom scenario_engine.dsl.actor_runtime import execute_actors_internal\nfrom scenario_engine.engine2 import construct_result2,canonical_result2_bytes\ns=compile_document(parse_yaml({raw!r}));o=execute_actors_internal(s,"root",7);print(canonical_result2_bytes(construct_result2(s,o)).hex())'''
    outputs = []
    for seed in ("1", "999"):
        env = os.environ.copy(); env.update({"PYTHONHASHSEED": seed, "PYTHONPATH": str(ROOT / "src")})
        outputs.append(subprocess.check_output([sys.executable, "-c", code], cwd=ROOT, env=env))
    assert outputs[0] == outputs[1]


def test_t54_legacy_run_scenario_remains_unsupported_for_dsl2() -> None:
    compiled, _, _ = produced()
    with pytest.raises(UnsupportedDSL2ExecutionError): run_scenario(compiled, "root")


def test_independent_literal_golden_vectors() -> None:
    _, outcome, result = produced()
    # These literals are independently SHA-256 checked, not generated twice as an oracle.
    assert result.manifest.manifest_hash == "99365d3d1f11113f342ad34d3585f677904a1c7392beb10d034b45abda3cd82d"
    assert result.result_hash == "3b14683c0549e1e066fb0a87aaf2eeac840f392aea397604ae47598d6097f552"
    assert hashlib.sha256(canonical_manifest2_identity_bytes(result.manifest)).hexdigest() == result.manifest.manifest_hash
    assert hashlib.sha256(canonical_result2_identity_bytes(result)).hexdigest() == result.result_hash
    assert canonical_schedule_bytes(outcome.schedule)
