from __future__ import annotations

import hashlib
import inspect
from importlib.resources import files
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

import scenario_engine
from scenario_engine.compatibility import CompatibilityClassification as C, classify_engine_contract
from scenario_engine.compatibility_fixtures import (
    export_engine2_compatibility_fixtures, read_engine2_fixture_manifest,
    verify_engine2_compatibility_fixtures,
)
from scenario_engine.engine2 import (
    Engine2EvidenceError, canonical_result2_bytes, execute_engine2, read_manifest2,
    read_result2, read_suite_run2, replay_engine2, validate_engine2,
)
from scenario_engine.schedule import canonical_schedule_bytes, read_schedule


ROOT = Path(__file__).parents[1]
PACK = Path(str(files("scenario_engine").joinpath("data/compatibility/phase5_10")))
LEGACY = Path(str(files("scenario_engine").joinpath("data/compatibility/phase4_11")))
LEGACY_MANIFEST_SHA256 = "4909bc5876bcf9add8f8444f7dcfb4b07153b9afea489226f30db86460d34187"
ROOT_EXPORTS = tuple(scenario_engine.__all__)


def invoke(*arguments: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[bytes]:
    runtime = os.environ.copy(); runtime["PYTHONPATH"] = str(ROOT / "src")
    if env: runtime.update(env)
    return subprocess.run([sys.executable, "-m", "scenario_engine.cli", *arguments], cwd=ROOT,
                          env=runtime, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


def test_t01_t05_public_api_signatures_and_root_are_frozen() -> None:
    assert tuple(scenario_engine.__all__) == ROOT_EXPORTS
    assert not {"validate_engine2", "execute_engine2", "replay_engine2", "classify_engine_contract"} & set(ROOT_EXPORTS)
    assert str(inspect.signature(validate_engine2)) == "(yaml_text: 'str') -> 'Any'"
    assert "schedule_seed: 'int'" in str(inspect.signature(execute_engine2))
    assert str(inspect.signature(classify_engine_contract)).startswith("(*, dsl_version:")


def test_t12_t17_fixture_inventory_integrity_native_read_and_export(tmp_path: Path) -> None:
    manifest = read_engine2_fixture_manifest()
    assert [item["id"] for item in manifest["fixtures"]] == [
        f"F{number:02d}-" + item["id"].split("-", 1)[1]
        for number, item in enumerate(manifest["fixtures"], 1)
    ]
    assert len(manifest["fixtures"]) == 30
    paths = verify_engine2_compatibility_fixtures()
    exported = export_engine2_compatibility_fixtures(tmp_path / "one")
    exported_two = export_engine2_compatibility_fixtures(tmp_path / "two")
    tree = lambda root: {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert tree(exported) == tree(exported_two) == tree(PACK)
    assert set(paths) == set(tree(PACK)) - {"compatibility-fixtures.json"}
    assert read_manifest2((PACK / "artifacts/manifest-v2.json").read_bytes()).contract == "scenario.manifest/2"
    assert read_result2((PACK / "artifacts/result-v2.json").read_bytes()).contract == "scenario.result/2"
    assert read_schedule((PACK / "artifacts/schedule-v1.json").read_bytes()).contract == "scenario.schedule/1"
    assert read_suite_run2((PACK / "artifacts/suite-run-v2.json").read_bytes()).contract == "suite.run/2"


def test_t15_t28_historical_fixture_integrity_unchanged() -> None:
    data = (LEGACY / "compatibility-fixtures.json").read_bytes()
    assert hashlib.sha256(data).hexdigest() == LEGACY_MANIFEST_SHA256
    manifest = json.loads(data)
    for item in (*manifest["fixtures"], *manifest["support_files"]):
        assert hashlib.sha256((LEGACY / item["path"]).read_bytes()).hexdigest() == item["sha256"]


def test_t18_native_exact_replay_and_fixed_golden_identities() -> None:
    scenario = validate_engine2((PACK / "scenarios/scenario-v2.yaml").read_text())
    result = read_result2((PACK / "artifacts/result-v2.json").read_bytes())
    schedule = read_schedule((PACK / "artifacts/schedule-v1.json").read_bytes())
    assert result.manifest.manifest_hash == "5e0d08254eaa276048c4b4fe1f6bae98b09eea2463f502a088f8cb8e66e15255"
    assert result.result_hash == "2af4ffc6cba69a37c5eb9940bc7caa9fffb8a1921f108f7fbbdabb04262100bf"
    assert schedule.schedule_hash == "c655a76cd9a5982c7960f25f2ee6b881968ea33a1ed6d68ec34133b7cde87b41"
    assert replay_engine2(result, schedule, scenario) == result


@pytest.mark.parametrize(("dsl", "engine", "contract", "operation", "expected"), (
    (1, "1.0.0", "scenario.result/1", "execute", C.SUPPORTED_EXACT),
    (1, "2.0.0", "scenario.result/1", "execute", C.UNSUPPORTED_CROSS_MAJOR),
    (2, "1.0.0", "scenario.result/2", "execute", C.UNSUPPORTED_CROSS_MAJOR),
    (2, "2.0.0", "scenario.result/2", "replay", C.SUPPORTED_EXACT),
    (1, "1.0.0", "scenario.result/2", "replay", C.UNSUPPORTED_CROSS_MAJOR),
    (1, "2.0.0", "scenario.result/1", "replay", C.UNSUPPORTED_CROSS_MAJOR),
    (1, "2.0.0", "scenario.result/1", "inspect", C.SUPPORTED_LEGACY_OPERATION),
    (2, "2.0.0", "scenario.result/999", "read", C.UNKNOWN_CONTRACT),
    (2, "999.0.0", "scenario.result/2", "replay", C.UNKNOWN_VERSION),
    (None, "2.0.0", "scenario.result/2", "replay", C.INCOMPLETE_COORDINATES),
    (2, "2.0.0", "scenario.result/2", "unknown", C.UNKNOWN_CONTRACT),
))
def test_t19_t35_complete_stable_compatibility_matrix(dsl, engine, contract, operation, expected) -> None:
    assert classify_engine_contract(dsl_version=dsl, engine_version=engine,
                                    result_contract=contract, operation=operation).classification is expected


def test_t22_t32_rejection_fixture_readers_fail_closed() -> None:
    invalid = sorted((PACK / "rejections").glob("*.json"))
    result_cases = [path for path in invalid if path.name not in {"mixed-contract-tuple.json", "unknown-contract.json"}]
    for path in result_cases:
        with pytest.raises(Engine2EvidenceError): read_result2(path.read_bytes())


def test_t06_t10_cli_seed_stream_exit_help_and_fixture_pack(tmp_path: Path) -> None:
    source = PACK / "scenarios/scenario-v2.yaml"
    missing = invoke("--json", "run", str(source), "--seed", "root", "--schedule-out", str(tmp_path / "s"))
    assert missing.returncode == 2 and missing.stdout == b""
    assert json.loads(missing.stderr)["code"] == "SCHEDULE_SEED_REQUIRED"
    help_result = invoke("run", "--help")
    assert help_result.returncode == 0 and b"--schedule-seed" in help_result.stdout and b"--schedule-out" in help_result.stdout
    exported = invoke("--json", "compatibility-fixtures", "export", "--pack", "phase5_10", "--out", str(tmp_path / "pack"))
    assert exported.returncode == 0 and exported.stderr == b""
    assert json.loads(exported.stdout)["schema"] == "scenario.compatibility-fixtures/2"


def test_t09_t39_t40_root_and_schedule_seed_are_independent_cross_process() -> None:
    source = (PACK / "scenarios/scenario-v2.yaml").read_text()
    code = ("from scenario_engine.engine2 import *;from scenario_engine.schedule import canonical_schedule_bytes;"
            f"s=validate_engine2({source!r});r,q=execute_engine2(s,'fixture-generation-root',17);"
            "print(canonical_result2_bytes(r).hex());print(canonical_schedule_bytes(q).hex())")
    outputs = []
    for hashseed in ("1", "999"):
        result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, stdout=subprocess.PIPE,
                                check=True, env={**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONHASHSEED": hashseed})
        outputs.append(result.stdout)
    assert outputs[0] == outputs[1]
    scenario = validate_engine2(source)
    one = execute_engine2(scenario, "root-a", 17)[1]
    two = execute_engine2(scenario, "root-b", 17)[1]
    three = execute_engine2(scenario, "root-a", 18)[1]
    assert one.execution.root_seed != two.execution.root_seed and one.schedule_seed == two.schedule_seed
    assert one.schedule_seed != three.schedule_seed
