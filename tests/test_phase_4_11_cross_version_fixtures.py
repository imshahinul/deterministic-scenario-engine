from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from scenario_engine.cli import CLIExitCode


ROOT = Path(__file__).parents[1]
CORPUS = ROOT / "tests/fixtures/phase4_11"
MANIFEST = CORPUS / "compatibility-fixtures.json"
SCENARIO = CORPUS / "scenarios/compatibility_case.yaml"
MISMATCH = CORPUS / "scenarios/mismatch_case.yaml"
STATUSES = {"SUPPORTED", "UNSUPPORTED", "MIGRATION_REQUIRED", "NOT_APPLICABLE"}
OPERATIONS = ("inspect", "verify", "replay", "migrate", "diff")
MAX_FIXTURE_BYTES = 16 * 1024


def invoke(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, "-m", "scenario_engine.cli", *args], cwd=ROOT,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        env={"PYTHONPATH": str(ROOT / "src")},
    )


@pytest.fixture(scope="module")
def fixture_manifest() -> dict:
    return json.loads(MANIFEST.read_bytes())


def records(manifest: dict) -> dict[str, dict]:
    return {item["id"]: item for item in manifest["fixtures"]}


def artifact(item: dict) -> Path:
    return CORPUS / item["path"]


def test_fixture_manifest_contract_structure_and_deterministic_matrix(fixture_manifest: dict) -> None:
    assert fixture_manifest["schema_version"] == "scenario.compatibility-fixtures/1"
    assert fixture_manifest["operation_order"] == list(OPERATIONS)
    ids = [item["id"] for item in fixture_manifest["fixtures"]]
    assert ids == sorted(ids) and len(ids) == len(set(ids))
    assert fixture_manifest["historical_corpus_absences"] == ["OLDER_INSPECTABLE_NOT_REPLAYABLE"]
    for item in fixture_manifest["fixtures"]:
        assert set(item) >= {"id", "artifact_contract", "source_version", "sha256", "classification",
                             "provenance", "path", "operations"}
        assert set(item) <= {"id", "artifact_contract", "source_version", "sha256", "classification",
                             "provenance", "path", "operations", "scenario_resource", "inputs_resource"}
        assert set(item["operations"]) == set(OPERATIONS)
        assert all(operation["status"] in STATUSES for operation in item["operations"].values())
        assert item["provenance"]["kind"] in {"HISTORICAL_FIXTURE", "SYNTHETIC_NEGATIVE_FIXTURE"}
    # Parsing and canonical re-encoding provide a deterministic matrix representation.
    assert json.dumps(fixture_manifest, sort_keys=True, separators=(",", ":")).encode() == MANIFEST.read_bytes()


def test_fixture_hashes_paths_uniqueness_bounds_and_security(fixture_manifest: dict) -> None:
    hashes = []
    paths = []
    for item in fixture_manifest["fixtures"] + fixture_manifest["support_files"]:
        path = CORPUS / item["path"]
        data = path.read_bytes()
        paths.append(item["path"])
        hashes.append(item["sha256"])
        assert path.is_file() and len(data) <= MAX_FIXTURE_BYTES
        assert hashlib.sha256(data).hexdigest() == item["sha256"]
        lowered = data.lower()
        assert all(token not in lowered for token in (
            b"/users/", b"/private/", b"authorization:", b"bearer ", b"api_key", b"password",
            b"github.com/imshahinul", b"localhost",
        ))
    assert len(paths) == len(set(paths))
    assert len(hashes) == len(set(hashes))
    committed = {path.relative_to(CORPUS).as_posix() for path in CORPUS.rglob("*") if path.is_file()}
    assert committed == {"compatibility-fixtures.json", *paths}


def test_current_and_historical_suite_fixtures_inspect_replay_and_diff(fixture_manifest: dict) -> None:
    indexed = records(fixture_manifest)
    current = artifact(indexed["current-2.1.2-suite-run-v1"])
    historical = artifact(indexed["historical-2.0.0-suite-run-v1"])
    for item in (indexed["current-2.1.2-suite-run-v1"], indexed["historical-2.0.0-suite-run-v1"]):
        path = artifact(item)
        scenario = CORPUS / item["scenario_resource"]
        inputs = (CORPUS / item["inputs_resource"]).read_text(encoding="utf-8")
        inspected = invoke("--json", "inspect", str(path), "--kind", "suite")
        replayed = invoke("--json", "replay", str(path), "--scenario", str(scenario),
                          "--inputs", inputs)
        assert inspected.returncode == replayed.returncode == CLIExitCode.SUCCESS
        assert json.loads(inspected.stdout)["target_kind"] == "run_manifest"
        assert json.loads(replayed.stdout)["state"] == json.loads(inputs)
    difference = invoke("--json", "diff", str(current), str(historical), "--kind", "suite", "--mode", "complete")
    assert difference.returncode == CLIExitCode.DIFFERENT
    assert json.loads(difference.stdout)["schema_version"] == "semantic.diff/1"


def test_historical_result_is_inspectable_diffable_migratable_but_not_replayable(
    fixture_manifest: dict, tmp_path: Path,
) -> None:
    item = records(fixture_manifest)["historical-1.0.0-result-v1"]
    path = artifact(item)
    inspected = invoke("--json", "inspect", str(path))
    difference = invoke("--json", "diff", str(path), str(path), "--mode", "complete")
    assert inspected.returncode == difference.returncode == CLIExitCode.SUCCESS
    assert json.loads(inspected.stdout)["target_kind"] == "v1_result"
    assert json.loads(difference.stdout)["equal"] is True
    destination = tmp_path / "migrated"
    migrated = invoke(
        "--json", "migrate", str(path), str(destination), "--artifact-kind", "result",
        "--schema-version", "scenario.result/1", "--product-version", "1.0.0",
        "--source-sha256", item["sha256"],
    )
    assert migrated.returncode == CLIExitCode.SUCCESS
    assert (destination / "artifacts/source.json").read_bytes() == path.read_bytes()
    assert json.loads(migrated.stdout)["transformations"] == ["wrap-v1-result-as-evidence/1"]
    assert item["operations"]["replay"] == {"reason": "ENGINE_VERSION_UNSUPPORTED", "status": "UNSUPPORTED"}

    replayed = invoke("--json", "replay", str(path), "--scenario", str(CORPUS / item["scenario_resource"]))
    error = json.loads(replayed.stderr)
    assert replayed.returncode == CLIExitCode.REPLAY_COMPATIBILITY and replayed.stdout == b""
    assert error["schema"] == "scenario.error/1"
    assert error["category"] == "REPLAY_COMPATIBILITY"
    assert error["code"] == "ENGINE_VERSION_UNSUPPORTED"


def test_missing_fixture_inputs_are_actionable_replay_diagnostics(fixture_manifest: dict) -> None:
    item = records(fixture_manifest)["current-2.1.2-suite-run-v1"]
    arguments = ("replay", str(artifact(item)), "--scenario", str(CORPUS / item["scenario_resource"]))
    human = invoke(*arguments)
    assert human.returncode == CLIExitCode.REPLAY_COMPATIBILITY and human.stdout == b""
    assert b"code=REPLAY_DATA_INCOMPLETE" in human.stderr
    assert b"next_action=PROVIDE_REQUIRED_REPLAY_INPUTS" in human.stderr
    assert b"Traceback" not in human.stderr
    machine = invoke("--json", *arguments)
    error = json.loads(machine.stderr)
    assert machine.returncode == CLIExitCode.REPLAY_COMPATIBILITY and machine.stdout == b""
    assert error["schema"] == "scenario.error/1"
    assert error["category"] == "REPLAY_COMPATIBILITY"
    assert error["code"] == "REPLAY_DATA_INCOMPLETE"
    assert error["remediation"] == "PROVIDE_REQUIRED_REPLAY_INPUTS"


def test_fixture_manifest_publishes_complete_replay_command_resources(fixture_manifest: dict) -> None:
    indexed = records(fixture_manifest)
    for fixture_id in ("current-2.1.2-suite-run-v1", "historical-2.0.0-suite-run-v1"):
        item = indexed[fixture_id]
        assert (CORPUS / item["scenario_resource"]).is_file()
        assert (CORPUS / item["inputs_resource"]).is_file()
    historical = indexed["historical-1.0.0-result-v1"]
    assert (CORPUS / historical["scenario_resource"]).is_file()
    assert "inputs_resource" not in historical


@pytest.mark.parametrize(("fixture_id", "reason"), (
    ("synthetic-incomplete-suite-run-v1", "REPLAY_DATA_INCOMPLETE"),
    ("synthetic-unknown-engine-suite-run-v1", "ENGINE_VERSION_UNSUPPORTED"),
    ("synthetic-unknown-manifest-suite-run-v9", "MANIFEST_VERSION_UNSUPPORTED"),
    ("synthetic-unsupported-contract", "MANIFEST_VERSION_UNSUPPORTED"),
    ("synthetic-scenario-mismatch-suite-run-v1", "SCENARIO_MISMATCH"),
))
def test_synthetic_replay_failures_are_closed_and_stable(
    fixture_manifest: dict, fixture_id: str, reason: str,
) -> None:
    item = records(fixture_manifest)[fixture_id]
    result = invoke("--json", "replay", str(artifact(item)), "--scenario", str(SCENARIO),
                    "--inputs", '{"selected":7}')
    assert result.returncode == CLIExitCode.REPLAY_COMPATIBILITY and result.stdout == b""
    error = json.loads(result.stderr)
    assert error["schema"] == "scenario.error/1" and error["code"] == reason
    assert error["details"]["migration"] == "MIGRATION_UNAVAILABLE"
    assert item["operations"]["replay"] == {"reason": reason, "status": "UNSUPPORTED"}


def test_inspectable_does_not_imply_replayable_and_unknown_states_fail_closed(fixture_manifest: dict) -> None:
    indexed = records(fixture_manifest)
    unknown_engine = indexed["synthetic-unknown-engine-suite-run-v1"]
    assert unknown_engine["operations"]["inspect"]["status"] == "SUPPORTED"
    assert unknown_engine["operations"]["replay"]["status"] == "UNSUPPORTED"
    for fixture_id in ("synthetic-unknown-engine-suite-run-v1", "synthetic-unknown-manifest-suite-run-v9"):
        assert indexed[fixture_id]["source_version"] == "UNKNOWN"
        assert indexed[fixture_id]["operations"]["replay"]["status"] == "UNSUPPORTED"


def test_verify_is_not_claimed_for_non_bundle_fixtures_and_migration_unavailable_is_explicit(
    fixture_manifest: dict,
) -> None:
    for item in fixture_manifest["fixtures"]:
        assert item["operations"]["verify"] == {"status": "NOT_APPLICABLE"}
    current = records(fixture_manifest)["current-2.1.2-suite-run-v1"]
    assert current["operations"]["migrate"] == {"reason": "MIGRATION_UNAVAILABLE", "status": "UNSUPPORTED"}


def test_scenario_mismatch_pair_is_explicit(fixture_manifest: dict) -> None:
    item = records(fixture_manifest)["synthetic-scenario-mismatch-suite-run-v1"]
    failed = invoke("--json", "replay", str(artifact(item)), "--scenario", str(SCENARIO),
                    "--inputs", '{"selected":7}')
    error = json.loads(failed.stderr)
    assert error["code"] == "SCENARIO_MISMATCH"
    assert error["details"]["scenario_expected"] == "mismatch_case"
    assert error["details"]["scenario_received"] == "compatibility_case"
    assert MISMATCH.read_text(encoding="utf-8").startswith("dsl_version: 1\nscenario: mismatch_case\n")
