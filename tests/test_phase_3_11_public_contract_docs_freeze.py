from __future__ import annotations

import hashlib
import importlib
from pathlib import Path
import re
import subprocess
import sys
import tomllib

import pytest

from scenario_engine._version import ENGINE_VERSION, VERSION
from scenario_engine.cli import CLIExitCode
from scenario_engine.evidence import CompatibilityCapability


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "docs/phase3-public-contract.md"
PUBLIC_DOCS = (
    ROOT / "README.md", ROOT / "docs/api.md", ROOT / "docs/determinism.md",
    ROOT / "docs/phase2-public-contract.md", CONTRACT,
    ROOT / "docs/phase3-architecture.md", ROOT / "docs/quickstart.md",
    ROOT / "docs/reproducibility.md", ROOT / "docs/security-and-non-goals.md",
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
    "scenario_engine.evidence": (95, "4b3f258c47ea896d4455fb56262b415d6dfeaa7a791a59e23d94349171f8cb7b"),
    "scenario_engine.reference_packs": (4, "9b81eb1663ef5da3215de5fd93f47e96bb76be4305d3fb5c33376f5220a44c01"),
}
COMMANDS = ("validate", "run", "replay", "hash", "inspect", "explain", "diff", "matrix", "batch", "export", "verify", "migrate")
PHASE3_SCHEMAS = {
    "evidence.bundle/1", "evidence.entry/1", "evidence.relationship/1",
    "evidence.provenance/1", "evidence.adapter-capability/1",
    "evidence.adapter-receipt/1", "evidence.compatibility-report/1",
    "evidence.migration-plan/1", "evidence.fixture-index/1",
}
TRANSFORMATIONS = {
    "wrap-v1-manifest-as-evidence/1", "wrap-v1-result-as-evidence/1",
    "wrap-v2-batch-as-evidence/1", "wrap-v2-composition-as-evidence/1",
    "wrap-v2-matrix-as-evidence/1", "wrap-v2-suite-as-evidence/1",
}


def test_all_public_manifests_and_documented_imports_are_frozen() -> None:
    contract = CONTRACT.read_text()
    for module_name, (count, expected_hash) in PUBLIC_MANIFESTS.items():
        module = importlib.import_module(module_name)
        exports = tuple(module.__all__)
        assert len(exports) == len(set(exports)) == count
        assert all(getattr(module, name) is not None for name in exports)
        digest = hashlib.sha256("\n".join(sorted(exports)).encode()).hexdigest()
        assert digest == expected_hash
        assert f"{module_name} count={count}" in contract
        assert f"{module_name} sha256={expected_hash}" in contract

    from scenario_engine.evidence import (  # noqa: F401
        ArtifactDescriptor, EvidenceBundle, EvidenceEntry, EvidenceProvenance,
        EvidenceRelationship, EvidenceType, compatibility_report,
        export_evidence_bundle, plan_migration, read_evidence_bundle,
    )
    from scenario_engine.reference_packs import (  # noqa: F401
        EcommerceEvidenceWorkflow, ecommerce_domain_pack,
        export_ecommerce_evidence,
    )


def test_cli_commands_help_entry_point_and_exit_codes_are_exact() -> None:
    cli_main = importlib.import_module("scenario_engine.cli.main")
    parser = cli_main._parser()
    choices = next(action.choices for action in parser._actions if action.choices)
    assert tuple(choices) == COMMANDS
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert metadata["project"]["scripts"] == {"scenario": "scenario_engine.cli:main"}
    assert {member.name: member.value for member in CLIExitCode} == {
        "SUCCESS": 0, "DIFFERENT": 1, "USAGE": 2, "VALIDATION": 3,
        "EXECUTION": 4, "REPLAY_COMPATIBILITY": 5, "SECURITY_OR_BOUND": 6,
        "IO": 7, "INTERNAL": 8,
    }
    process = subprocess.run(
        [sys.executable, "-m", "scenario_engine.cli", "--help"], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    assert process.returncode == 0 and process.stderr == ""
    assert all(command in process.stdout for command in COMMANDS)


@pytest.mark.parametrize("command", ("verify", "export", "migrate"))
def test_phase3_cli_help_is_documented_and_clean(command: str) -> None:
    process = subprocess.run(
        [sys.executable, "-m", "scenario_engine.cli", command, "--help"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert process.returncode == 0
    assert f"scenario {command}" in process.stdout
    assert process.stderr == ""


def test_schemas_capabilities_routes_and_errors_are_frozen() -> None:
    import scenario_engine.evidence as evidence
    compatibility = importlib.import_module("scenario_engine.evidence.compatibility")
    migration = importlib.import_module("scenario_engine.evidence.migration")
    schemas = {
        evidence.EVIDENCE_BUNDLE_SCHEMA_VERSION,
        evidence.EVIDENCE_ENTRY_SCHEMA_VERSION,
        evidence.EVIDENCE_RELATIONSHIP_SCHEMA_VERSION,
        evidence.EVIDENCE_PROVENANCE_SCHEMA_VERSION,
        evidence.EVIDENCE_ADAPTER_CAPABILITY_SCHEMA_VERSION,
        evidence.EVIDENCE_ADAPTER_RECEIPT_SCHEMA_VERSION,
        evidence.EVIDENCE_COMPATIBILITY_REPORT_SCHEMA_VERSION,
        evidence.EVIDENCE_MIGRATION_PLAN_SCHEMA_VERSION,
        evidence.FIXTURE_INDEX_SCHEMA_VERSION,
    }
    assert schemas == PHASE3_SCHEMAS
    assert [item.name for item in CompatibilityCapability] == [
        "READABLE", "INSPECTABLE", "DIFFABLE", "EXECUTABLE", "REPLAYABLE",
        "MIGRATABLE", "UNSUPPORTED",
    ]
    assert set(migration._EXECUTABLE_TRANSFORMATIONS) == TRANSFORMATIONS
    assert len(compatibility._ROUTES) == 6
    for name in evidence.__all__:
        if name.endswith("Error"):
            error = getattr(evidence, name)
            assert issubclass(error, Exception)
            assert error.__module__.startswith("scenario_engine.evidence")
    contract = CONTRACT.read_text()
    assert all(schema in contract for schema in PHASE3_SCHEMAS)
    assert all(route in contract for route in TRANSFORMATIONS)
    assert "not a separately\nversioned persisted schema" in contract


def test_phase3_bounds_match_source_and_contract() -> None:
    import scenario_engine.evidence as evidence
    expected = {
        "MAX_BUNDLE_ENTRIES": 100000, "MAX_BUNDLE_RELATIONSHIPS": 100000,
        "MAX_BUNDLE_INDEX_BYTES": 16 << 20, "MAX_ARTIFACT_BYTES": 256 << 20,
        "DEFAULT_AGGREGATE_BUNDLE_BYTES": 256 << 20,
        "MAX_AGGREGATE_BUNDLE_BYTES": 4 << 30, "MAX_BUNDLE_PATH_DEPTH": 64,
        "MAX_BUNDLE_INDEX_DEPTH": 64, "MAX_JSONL_RECORDS": 100000,
        "DEFAULT_ADAPTER_IN_FLIGHT": 64, "MAX_ADAPTER_IN_FLIGHT": 1024,
        "MAX_ADAPTER_RECEIPT_BYTES": 1 << 20,
        "MAX_ADAPTER_RECEIPTS_BYTES": 16 << 20, "MAX_MIGRATION_STEPS": 1000,
    }
    assert {name: getattr(evidence, name) for name in expected} == expected
    contract = CONTRACT.read_text()
    for text in ("100,000", "16 MiB", "256 MiB", "4 GiB", "1,024", "1,000"):
        assert text in contract


def test_versions_publication_security_reference_and_links_are_frozen(tmp_path: Path) -> None:
    from scenario_engine import compile_document, parse_yaml, run_scenario
    from scenario_engine.reference_packs import ecommerce_domain_pack, export_ecommerce_evidence

    result = run_scenario(compile_document(parse_yaml((ROOT / "examples/cart.yaml").read_text())), "phase3.11")
    assert VERSION == "2.1.1" and ENGINE_VERSION == "1.0.0"
    assert result.manifest.engine_version == "1.0.0" and result.manifest.dsl_version == 1
    contract = CONTRACT.read_text()
    assert "current source distribution version=2.1.0" in contract
    assert "2.1.0, which is not published" in contract
    assert ecommerce_domain_pack().content_hash == "987651d083d7c87696ef10c377080e08a173a56bd64aa6114262e5f6e0c35bb6"
    workflow = export_ecommerce_evidence(tmp_path / "ecommerce-bundle")
    assert workflow.bundle.bundle_id == "db145c19d041ffbed668404a8945604e735d9db42c8f75068d657ba4a0c4c507"

    combined = "\n".join(path.read_text() for path in PUBLIC_DOCS)
    stale = re.compile(r"(?:2\.0\.0|Phase 2)[^\n]{0,50}(?:is )?unpublished|no (?:PyPI|GitHub)[^\n]{0,30}(?:2\.0\.0|release)", re.I)
    assert stale.search(combined) is None
    for statement in (
        "Evidence bundles are untrusted input", "not sandboxed",
        "no adapter/provider discovery", "no network",
        "recursive or lossy migration", "distributed scheduling",
    ):
        assert statement.lower() in combined.lower()
    for target in re.findall(r"\[[^]]+\]\(([^)#]+\.md)(?:#[^)]+)?\)", combined):
        if "://" in target:
            continue
        assert (ROOT / "docs" / target).resolve().is_file() or (ROOT / target).resolve().is_file()
