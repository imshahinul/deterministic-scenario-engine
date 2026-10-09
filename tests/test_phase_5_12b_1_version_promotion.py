from __future__ import annotations

from hashlib import sha256
from importlib.metadata import version as distribution_version
from importlib.resources import files
import json
from pathlib import Path
import subprocess
import sys

import pytest

import scenario_engine
from scenario_engine._version import ENGINE1_VERSION, ENGINE_VERSION, VERSION
from scenario_engine.compatibility import CompatibilityClassification as C, classify_engine_contract
from scenario_engine.compatibility_fixtures import (
    read_engine2_fixture_manifest, verify_engine2_compatibility_fixtures,
)
from scenario_engine.dsl import compile_document, parse_yaml, replay_scenario, run_scenario
from scenario_engine.engine2 import read_result2, replay_engine2, validate_engine2
from scenario_engine.schedule import ENGINE2_EXECUTION_VERSION, read_schedule
from scenario_engine.values import canonical_bytes


ROOT = Path(__file__).parents[1]
PACK1 = Path(str(files("scenario_engine").joinpath("data/compatibility/phase4_11")))
PACK2 = Path(str(files("scenario_engine").joinpath("data/compatibility/phase5_10")))
DSL1 = (ROOT / "examples/cart.yaml").read_text(encoding="utf-8")
RESULT1_SHA256 = "cffc2e482f304ab18d39f96166e3e1be78b117a86bf0ce8ad0e22973677001b5"
MANIFEST1_SHA256 = "397803be425ca3af4020196346fc98f0f14c6eda495fbfa3a0c2c88a51dd10ba"
PACK1_INDEX_SHA256 = "4909bc5876bcf9add8f8444f7dcfb4b07153b9afea489226f30db86460d34187"


def test_t01_t06_version_roles_are_separate_and_exact() -> None:
    assert VERSION == "3.0.0"
    assert scenario_engine.ENGINE_VERSION == ENGINE_VERSION == ENGINE2_EXECUTION_VERSION == "2.0.0"
    assert ENGINE1_VERSION == "1.0.0"
    result1 = run_scenario(compile_document(parse_yaml(DSL1)), "s")
    result2 = read_result2((PACK2 / "artifacts/result-v2.json").read_bytes())
    assert (result1.manifest.engine_version, result1.manifest.dsl_version) == ("1.0.0", 1)
    assert (result2.manifest.engine_version, result2.manifest.dsl_version) == ("2.0.0", 2)


def test_t07_t10_engine1_golden_manifest_suite_and_replay_are_unchanged() -> None:
    result = run_scenario(compile_document(parse_yaml(DSL1)), "s")
    assert sha256(result.to_json_bytes()).hexdigest() == RESULT1_SHA256
    assert sha256(canonical_bytes(result.manifest.normalized())).hexdigest() == MANIFEST1_SHA256
    assert replay_scenario(DSL1, result.manifest).to_json_bytes() == result.to_json_bytes()
    suite = json.loads((PACK1 / "artifacts/current-2.1.2-suite-run-v1.json").read_bytes())
    assert suite["schema_version"] == "suite.run/1"


def test_t11_t14_engine2_exact_replay_goldens_and_seed_independence() -> None:
    result = read_result2((PACK2 / "artifacts/result-v2.json").read_bytes())
    schedule = read_schedule((PACK2 / "artifacts/schedule-v1.json").read_bytes())
    scenario = validate_engine2((PACK2 / "scenarios/scenario-v2.yaml").read_text(encoding="utf-8"))
    assert replay_engine2(result, schedule, scenario) == result
    assert result.result_hash == "2af4ffc6cba69a37c5eb9940bc7caa9fffb8a1921f108f7fbbdabb04262100bf"
    assert schedule.schedule_hash == "c655a76cd9a5982c7960f25f2ee6b881968ea33a1ed6d68ec34133b7cde87b41"
    assert result.manifest.root_seed == "fixture-generation-root"
    assert result.manifest.schedule_seed == schedule.schedule_seed == 17


@pytest.mark.parametrize(("dsl", "engine", "contract", "expected"), (
    (1, "2.0.0", "scenario.result/1", C.UNSUPPORTED_CROSS_MAJOR),
    (2, "1.0.0", "scenario.result/2", C.UNSUPPORTED_CROSS_MAJOR),
    (None, "2.0.0", "scenario.result/2", C.INCOMPLETE_COORDINATES),
    (2, "999.0.0", "scenario.result/2", C.UNKNOWN_VERSION),
))
def test_t15_t16_cross_major_unknown_and_incomplete_fail_closed(dsl, engine, contract, expected) -> None:
    decision = classify_engine_contract(
        dsl_version=dsl, engine_version=engine, result_contract=contract, operation="replay",
    )
    assert decision.classification is expected


def test_t17_t18_fixture_pack_integrity() -> None:
    index = (PACK1 / "compatibility-fixtures.json").read_bytes()
    assert sha256(index).hexdigest() == PACK1_INDEX_SHA256
    legacy = json.loads(index)
    for item in (*legacy["fixtures"], *legacy["support_files"]):
        assert sha256((PACK1 / item["path"]).read_bytes()).hexdigest() == item["sha256"]
    assert len(read_engine2_fixture_manifest()["fixtures"]) == 30
    verify_engine2_compatibility_fixtures()


def test_t19_t23_public_import_cli_and_packaging_inputs() -> None:
    assert "ENGINE_VERSION" in scenario_engine.__all__
    help_result = subprocess.run(
        [sys.executable, "-m", "scenario_engine.cli", "run", "--help"],
        capture_output=True, check=False,
    )
    assert help_result.returncode == 0 and b"--schedule-seed" in help_result.stdout
    manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")
    assert "recursive-include docs *.md" in manifest
    assert (ROOT / "docs/release-notes-3.0.0.md").is_file()
    assert (ROOT / "docs/dsl2-reference.md").is_file()


def test_t22_installed_distribution_metadata_matches_source() -> None:
    assert distribution_version("deterministic-scenario-engine") == VERSION


def test_t25_t26_historical_tag_unchanged_and_no_release_tag() -> None:
    old = subprocess.check_output(["git", "rev-parse", "refs/tags/2.2.0^{commit}"], cwd=ROOT, text=True).strip()
    assert old == "aaa0495239df9db093c5e42d817a9d449e5ea055"
    assert subprocess.run(["git", "show-ref", "--verify", "--quiet", "refs/tags/3.0.0"], cwd=ROOT).returncode != 0
