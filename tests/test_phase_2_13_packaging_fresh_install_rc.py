from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import importlib
from pathlib import Path
import subprocess
import sys
import tomllib

import pytest

import scenario_engine
from scenario_engine import ENGINE_VERSION, compile_document, parse_yaml, replay_scenario, run_scenario
from scenario_engine._version import VERSION
from scenario_engine.diff import semantic_diff
from scenario_engine.inspection import inspect_result
from scenario_engine.manifest import ReplayCompatibilityError


ROOT = Path(__file__).resolve().parents[1]
GOLDENS = {
    "cart": "cffc2e482f304ab18d39f96166e3e1be78b117a86bf0ce8ad0e22973677001b5",
    "control": "86511d8c750272283eb1039a6e1039c8faa11cb5945c76aec41d9f5a71588e2b",
    "oracle": "5760aee1293d2d264d841621de08734358b3eb4ca54ef3e08e5a0b97f8f16cdd",
}
PUBLIC_MANIFESTS = {
    "scenario_engine": (33, "f19f9c8ebe3fd5574550fea1fdefc5a20fa004a4913978e8bf5ab1e447278a50"),
    "scenario_engine.suite": (44, "7db8a4edf260d1d16960203dfa43672d1d9cb8e4eed1624be87a9201ded59512"),
    "scenario_engine.composition": (29, "689f1fecb3bbbe4822ce523e09084857f9da625a31b4b1e9bbc447d3bc425fe7"),
    "scenario_engine.matrix": (25, "90611e656a435284db4b92dac84e1aa4d6b55b5a2172094ed3fa8598c86f15b3"),
    "scenario_engine.batch": (32, "59876678a4f4349a66b6caff4583e3cf8eb02425e3c7fc2b47d047edab1ad834"),
    "scenario_engine.inspection": (33, "3019b2a100afc8db8cb3272d38e24459be9929f785b6a6cf0c4c1a6bfb7f63ab"),
    "scenario_engine.diff": (24, "281136c0d1ba298a2be91344be9a9b1f380d3519e2c18f05b7ad8383470c3c0e"),
    "scenario_engine.cli": (2, "28361a19b5501e0631da3e10a8fa676b6aa37d7ab0e1faf54e5a5bc4b3f186a3"),
    "scenario_engine.domain_packs": (14, "d62dec3381ceba87d6f1231304b9b21779d0570171cba40b7905615cea8e7a6a"),
    "scenario_engine.oracle_assertions": (25, "bf3b83ed474567f02b6d796fce898e13f766740b599bb69f7258ca7e95514dc6"),
}


def _result(name: str, seed: str, inputs=None, *, disable_fault: bool = False):
    text = (ROOT / "examples" / name).read_text(encoding="utf-8")
    if disable_fault:
        text = text.replace("enabled: true", "enabled: false")
    return text, run_scenario(compile_document(parse_yaml(text)), seed, inputs=inputs)


def _cases():
    return {
        "cart": _result("cart.yaml", "s"),
        "control": _result("control_flow.yaml", "s", {
            "premium": True, "retry_count": 2, "customer_id": "customer-1",
        }),
        "oracle": _result("oracle_fault.yaml", "phase1.0c", disable_fault=True),
    }


def test_version_roles_are_explicit_and_dsl_remains_one() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert config["tool"]["setuptools"]["dynamic"]["version"]["attr"] == "scenario_engine._version.VERSION"
    assert VERSION == "2.1.1"
    assert ENGINE_VERSION == scenario_engine.ENGINE_VERSION == "1.0.0"
    _, result = _result("cart.yaml", "s")
    assert result.manifest.engine_version == "1.0.0"
    assert result.manifest.dsl_version == 1
    assert "VERSION" not in scenario_engine.__all__


def test_frozen_results_remain_byte_identical() -> None:
    for name, (_, result) in _cases().items():
        assert sha256(result.to_json_bytes()).hexdigest() == GOLDENS[name]
        assert result.to_json_bytes() == result.to_json_bytes()


def test_current_results_are_inspectable_diffable_and_replay_compatible() -> None:
    text, result = _result("cart.yaml", "s")
    assert inspect_result(result).target_kind == "v1_result"
    assert semantic_diff(result, result).equal
    assert replay_scenario(text, result.manifest).to_json_bytes() == result.to_json_bytes()
    incompatible = replace(result.manifest, engine_version="2.0.0")
    with pytest.raises(ReplayCompatibilityError, match="engine_version mismatch"):
        replay_scenario(text, incompatible)


def test_cli_inspect_and_diff_accept_current_results(tmp_path: Path) -> None:
    _, result = _result("cart.yaml", "s")
    result_path = tmp_path / "result.json"
    result_path.write_bytes(result.to_json_bytes())
    for args in (
        ("--json", "inspect", str(result_path), "--kind", "result"),
        ("--json", "diff", str(result_path), str(result_path), "--kind", "result"),
    ):
        process = subprocess.run(
            [sys.executable, "-m", "scenario_engine.cli", *args], cwd=ROOT,
            capture_output=True, check=False,
        )
        assert process.returncode == 0, process.stderr.decode()
        assert process.stderr == b""


def test_phase_2_12_public_manifests_are_unchanged() -> None:
    for module_name, (count, expected_hash) in PUBLIC_MANIFESTS.items():
        exports = tuple(importlib.import_module(module_name).__all__)
        assert len(exports) == count
        assert sha256("\n".join(sorted(exports)).encode()).hexdigest() == expected_hash


def test_entry_points_and_release_candidate_wording_are_preserved() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert config["project"]["scripts"] == {"scenario": "scenario_engine.cli:main"}
    assert config["project"]["entry-points"]["pytest11"] == {
        "scenario_engine": "scenario_engine.pytest_plugin",
    }
    docs = "\n".join((ROOT / path).read_text(encoding="utf-8") for path in (
        "README.md", "docs/phase2-public-contract.md",
    )).lower()
    # HISTORICAL_CHECKPOINT_FACT: 2.0.0 was an unpublished release candidate
    # when this packaging checkpoint was created.
    # CURRENT_DOCUMENTATION_CONTRACT: the package README remains neutral about
    # transient publication state while historical contracts remain immutable.
    assert "unpublished 2.0.0 release candidate" not in docs
    assert "no pypi or github release has occurred yet" not in docs
    assert "2.1.1" in docs
