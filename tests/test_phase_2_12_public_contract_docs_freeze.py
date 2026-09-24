from __future__ import annotations

import hashlib
import importlib
from pathlib import Path
import subprocess
import sys
import tomllib

import pytest

from scenario_engine._version import VERSION
from scenario_engine.cli import CLIExitCode
from scenario_engine.oracle_assertions import OracleAssertionKind


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DOCS = (
    ROOT / "README.md",
    ROOT / "docs/api.md",
    ROOT / "docs/compatibility.md",
    ROOT / "docs/determinism.md",
    ROOT / "docs/phase2-public-contract.md",
    ROOT / "docs/quickstart.md",
    ROOT / "docs/reproducibility.md",
    ROOT / "docs/security-and-non-goals.md",
    ROOT / "docs/testing-oracle.md",
)

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


def test_public_all_manifests_and_imports_are_frozen() -> None:
    for module_name, (count, expected_hash) in PUBLIC_MANIFESTS.items():
        module = importlib.import_module(module_name)
        exports = tuple(module.__all__)
        assert len(exports) == count
        assert len(exports) == len(set(exports))
        assert all(getattr(module, name) is not None for name in exports)
        digest = hashlib.sha256("\n".join(sorted(exports)).encode()).hexdigest()
        assert digest == expected_hash


def test_versions_errors_commands_and_entry_points_are_frozen() -> None:
    from scenario_engine import ReplayCompatibilityError, ScenarioEngineError
    from scenario_engine.composition import COMPOSITION_CONTRACT_VERSION
    from scenario_engine.diff import DIFF_SCHEMA_VERSION
    from scenario_engine.domain_packs import DOMAIN_PACK_SCHEMA_VERSION
    from scenario_engine.inspection import INSPECTION_SCHEMA_VERSION
    from scenario_engine.matrix import MATRIX_PLAN_CONTRACT_VERSION
    from scenario_engine.oracle_assertions import ORACLE_ASSERTION_SCHEMA_VERSION
    from scenario_engine.suite import READ_SCHEMA_VERSION, SUITE_SCHEMA_VERSION

    assert VERSION == "2.1.2"
    assert (COMPOSITION_CONTRACT_VERSION, MATRIX_PLAN_CONTRACT_VERSION) == (
        "composition.modules/1", "matrix.plan/1")
    assert (READ_SCHEMA_VERSION, SUITE_SCHEMA_VERSION) == (
        "suite.artifact-read/1", "suite.manifest/1")
    assert (INSPECTION_SCHEMA_VERSION, DIFF_SCHEMA_VERSION) == (
        "inspection.document/1", "semantic.diff/1")
    assert (DOMAIN_PACK_SCHEMA_VERSION, ORACLE_ASSERTION_SCHEMA_VERSION) == (
        "domain-pack/1", "oracle.assertion/1")
    assert issubclass(ReplayCompatibilityError, ScenarioEngineError)
    assert {member.value for member in CLIExitCode} == set(range(9))

    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert metadata["project"]["scripts"] == {"scenario": "scenario_engine.cli:main"}
    assert metadata["project"]["entry-points"]["pytest11"] == {
        "scenario_engine": "scenario_engine.pytest_plugin"}


def test_documented_assertion_kinds_and_bounds_match_source() -> None:
    from scenario_engine import batch, composition, diff, domain_packs, inspection, matrix
    cli_main = importlib.import_module("scenario_engine.cli.main")
    from scenario_engine.oracle_assertions import (
        MAX_ASSERTIONS, MAX_ASSERTION_BYTES, MAX_ASSERTION_PATH_DEPTH,
        MAX_ASSERTION_SCAN_RECORDS,
    )

    assert {kind.value for kind in OracleAssertionKind} == {
        "equal", "not_equal", "present", "absent", "count",
        "ordered_subsequence", "occurrence_count", "transition_occurrence",
        "transition_order", "logical_time",
    }
    expected = {
        "Composition": (composition.MAX_MODULES, composition.MAX_ROOT_DOCUMENT_BYTES,
                        composition.MAX_MODULE_DOCUMENT_BYTES,
                        composition.MAX_AGGREGATE_INPUT_BYTES,
                        composition.MAX_CANONICAL_COMPOSED_BYTES),
        "Matrix": (matrix.MAX_DIMENSIONS, matrix.MAX_VALUES_PER_DIMENSION,
                   matrix.MAX_RAW_CARDINALITY, matrix.MAX_RETAINED_CASES),
        "Batch": (batch.MAX_BATCH_ITEMS, batch.MAX_WORKERS, batch.MAX_IN_FLIGHT,
                  batch.DEFAULT_RETAINED_RESULT_BYTES),
        "Inspection": (inspection.MAX_INSPECTION_SECTIONS,
                       inspection.MAX_INSPECTION_RECORDS,
                       inspection.MAX_EXPLANATION_RECORDS,
                       inspection.MAX_INSPECTION_DEPTH, inspection.MAX_INSPECTION_BYTES),
        "Diff": (diff.DEFAULT_MAX_DIFF_RECORDS, diff.HARD_MAX_DIFF_RECORDS,
                 diff.MAX_DIFF_DEPTH, diff.MAX_COMPARED_ITEMS, diff.MAX_DIFF_BYTES),
        "Domain Packs": (domain_packs.MAX_PACKS_PER_REGISTRY,
                         domain_packs.MAX_ASSETS_PER_PACK,
                         domain_packs.MAX_CANONICAL_PACK_BYTES),
        "Oracle Assertions": (MAX_ASSERTIONS, MAX_ASSERTION_PATH_DEPTH,
                              MAX_ASSERTION_SCAN_RECORDS, MAX_ASSERTION_BYTES),
        "CLI": (cli_main.MAX_CLI_INPUT_BYTES, cli_main.MAX_AUXILIARY_JSON_BYTES,
                cli_main.MAX_RENDERED_OUTPUT_BYTES, cli_main.MAX_DIAGNOSTIC_CHARS),
    }
    assert expected == {
        "Composition": (64, 1 << 20, 1 << 20, 16 << 20, 16 << 20),
        "Matrix": (16, 1000, 100000, 10000),
        "Batch": (10000, 64, 64, 256 << 20),
        "Inspection": (32, 100000, 100000, 64, 256 << 20),
        "Diff": (10000, 100000, 64, 1000000, 256 << 20),
        "Domain Packs": (1000, 10000, 16 << 20),
        "Oracle Assertions": (1000, 64, 100000, 1 << 20),
        "CLI": (16 << 20, 1 << 20, 256 << 20, 4096),
    }


@pytest.mark.parametrize("command", (
    "validate", "run", "replay", "hash", "inspect", "explain", "diff",
    "matrix", "batch",
))
def test_all_documented_cli_commands_have_help(command: str) -> None:
    process = subprocess.run(
        [sys.executable, "-m", "scenario_engine.cli", command, "--help"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert process.returncode == 0
    assert f"scenario {command}" in process.stdout
    assert process.stderr == ""


def test_quickstart_cli_examples_execute(tmp_path: Path) -> None:
    result_path = tmp_path / "result.json"
    commands = (
        ["validate", "examples/cart.yaml"],
        ["--json", "hash", "examples/cart.yaml"],
        ["--json", "run", "examples/cart.yaml", "--seed", "quickstart", "--run-index", "0"],
    )
    outputs = []
    for args in commands:
        process = subprocess.run(
            [sys.executable, "-m", "scenario_engine.cli", *args], cwd=ROOT,
            capture_output=True, check=False,
        )
        assert process.returncode == 0, process.stderr.decode()
        assert process.stderr == b""
        outputs.append(process.stdout)
    result_path.write_bytes(outputs[-1])
    for args in (
        ["--json", "inspect", str(result_path), "--kind", "result"],
        ["--json", "diff", str(result_path), str(result_path), "--kind", "result", "--mode", "first"],
        ["--json", "matrix", "examples/cart.yaml", "--seed", "quickstart",
         "--dimensions", '[{"name":"region","values":["us","eu"]}]', "--describe"],
    ):
        process = subprocess.run(
            [sys.executable, "-m", "scenario_engine.cli", *args], cwd=ROOT,
            capture_output=True, check=False,
        )
        assert process.returncode == 0, process.stderr.decode()
        assert process.stdout.endswith(b"\n") and process.stderr == b""


def test_public_docs_security_release_and_paths_are_consistent() -> None:
    combined = "\n".join(path.read_text() for path in PUBLIC_DOCS)
    contract = (ROOT / "docs/phase2-public-contract.md").read_text()
    for command in ("validate", "run", "replay", "hash", "inspect", "explain",
                    "diff", "matrix", "batch"):
        assert f"scenario {command}" in contract
    for required in (
        "no automatic discovery", "pack dependency mechanism", "does not promise",
        "arbitrary Python execution", "hidden randomness", "wall-clock",
        "hidden network", "dynamic YAML imports", "global registries",
        "recursive subflows", "unbounded loops", "DB-backed", "ORM-owned",
        "raw SQL DSL", "automatic Schemathesis HTTP", "implicit environmental",
    ):
        assert required.lower() in combined.lower()
    assert "2.0.0 is published" not in combined.lower()
    assert "/Users/" not in combined and "$HOME/" not in combined
    for relative in ("examples/cart.yaml", "docs/phase2-public-contract.md"):
        assert (ROOT / relative).exists()
