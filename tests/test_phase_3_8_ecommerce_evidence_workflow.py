from __future__ import annotations

import ast
import json
from pathlib import Path

from scenario_engine.cli import main
from scenario_engine.diff import canonical_diff_bytes, semantic_diff
from scenario_engine.domain_packs import DomainPack, DomainPackRegistry
from scenario_engine.evidence import read_evidence_bundle
from scenario_engine.inspection import canonical_inspection_bytes
from scenario_engine.oracle_assertions import (
    ORACLE_EVALUATION_SCHEMA_VERSION,
    OracleAssertionOutcome,
    canonical_evaluation_bytes,
)
from scenario_engine.reference_packs.ecommerce import ecommerce_registry
from scenario_engine.reference_packs.ecommerce_evidence import (
    DOMAIN_PACK_NAME,
    DOMAIN_PACK_VERSION,
    ecommerce_domain_pack,
    export_ecommerce_evidence,
)


PACK_HASH = "987651d083d7c87696ef10c377080e08a173a56bd64aa6114262e5f6e0c35bb6"
BUNDLE_ID = "db145c19d041ffbed668404a8945604e735d9db42c8f75068d657ba4a0c4c507"
ARTIFACT_HASHES = {
    "baseline-variant.diff": "15f2133e6ca62af5dcf05790c2071d720d3a5a03d24a48085a201cac8a332469",
    "baseline.evaluation": "ec820e86220674dbaa565904ba43b5679d2daf6f0e3d6b2e774e343d78e424b2",
    "baseline.inspection": "525761aa8b1bbac2724ec75530013884a032de2b561d4cd899b3fcb3591e148e",
    "baseline.manifest": "533ca9f2d84f487af69fbcd4a768b2e60add3ed1ad4f5c16385d0e77fc86ab90",
    "baseline.result": "8715607e0f1978848f01c0c06ed57c1151934559465147cecc5274133396354a",
    "variant.result": "fe921211be3f347c54a2837143a52fddf0099bdab9f6bf3bf925b913e9984695",
}


def tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*") if path.is_file()
    }


def test_domain_pack_is_fresh_declarative_exact_and_plugin_compatible() -> None:
    first, second = ecommerce_domain_pack(), ecommerce_domain_pack()
    assert isinstance(first, DomainPack) and first is not second and first == second
    assert first.coordinate == f"{DOMAIN_PACK_NAME}@{DOMAIN_PACK_VERSION}"
    assert first.content_hash == PACK_HASH
    assert tuple((item.name, item.version) for item in first.plugin_requirements) == (
        ("ecommerce.customer_email", "1"),
        ("ecommerce.order_number", "1"),
        ("ecommerce.sku", "1"),
        ("ecommerce.tracking_number", "1"),
    )
    DomainPackRegistry((first,)).validate_plugins(first, ecommerce_registry())
    assert set(first.resource_templates) == {"baseline", "variant"}
    assert set(first.oracle_fragments) == {"lifecycle"}
    assert set(first.documentation) == {"scenario.dsl1"}


def test_end_to_end_replay_inspection_assertions_and_diff(tmp_path: Path) -> None:
    workflow = export_ecommerce_evidence(tmp_path / "bundle")
    assert workflow.baseline == workflow.replay
    assert workflow.baseline.to_json_bytes() == workflow.replay.to_json_bytes()
    assert workflow.baseline.manifest.domain_pack_versions == {}
    assert workflow.baseline.final_state["status"] == "shipped"
    assert workflow.baseline.final_state["paid"] is True
    assert canonical_inspection_bytes(workflow.inspection).hex()
    assert workflow.evaluation.schema_version == ORACLE_EVALUATION_SCHEMA_VERSION
    assert all(item.outcome is OracleAssertionOutcome.PASS for item in workflow.evaluation.results)
    assert canonical_evaluation_bytes(workflow.evaluation).hex()
    assert not workflow.difference.equal
    assert len(workflow.difference.records) <= 64
    repeated = semantic_diff(workflow.baseline, workflow.variant, max_records=64)
    assert canonical_diff_bytes(workflow.difference) == canonical_diff_bytes(repeated)
    assert any("customer_email" in item.path for item in workflow.difference.records)


def test_bundle_identity_relationships_readback_and_repeatable_export(tmp_path: Path) -> None:
    first = export_ecommerce_evidence(tmp_path / "one")
    second = export_ecommerce_evidence(tmp_path / "two")
    assert first.bundle.bundle_id == second.bundle.bundle_id == BUNDLE_ID
    assert {entry.logical_id: entry.sha256 for entry in first.bundle.entries} == ARTIFACT_HASHES
    assert read_evidence_bundle(
        tmp_path / "one/bundle.json", bundle_root=tmp_path / "one"
    ) == first.bundle
    assert tree_bytes(tmp_path / "one") == tree_bytes(tmp_path / "two")
    assert {(item.source_id, item.target_id, item.kind) for item in first.bundle.relationships} == {
        ("baseline.result", "baseline.inspection", "derived-inspection"),
        ("baseline.inspection", "baseline.evaluation", "evaluated-by-oracle"),
        ("baseline.result", "baseline-variant.diff", "compared-by-diff"),
        ("variant.result", "baseline-variant.diff", "compared-by-diff"),
    }


def test_in_process_cli_verify_and_export_are_deterministic(
    tmp_path: Path, capsys,
) -> None:
    workflow = export_ecommerce_evidence(tmp_path / "source")
    assert main(["--json", "verify", str(tmp_path / "source")]) == 0
    first = capsys.readouterr()
    assert main(["--json", "verify", str(tmp_path / "source")]) == 0
    second = capsys.readouterr()
    assert first.err == second.err == "" and first.out == second.out
    assert json.loads(first.out)["bundle_id"] == workflow.bundle.bundle_id
    assert main([
        "--json", "export", str(tmp_path / "source"), str(tmp_path / "copy")
    ]) == 0
    exported = json.loads(capsys.readouterr().out)
    assert exported["bundle_id"] == workflow.bundle.bundle_id
    assert main(["--json", "verify", str(tmp_path / "copy")]) == 0
    assert json.loads(capsys.readouterr().out)["verified"] is True
    assert tree_bytes(tmp_path / "source") == tree_bytes(tmp_path / "copy")


def test_reference_source_preserves_explicit_trust_and_authority_boundaries() -> None:
    root = Path(__file__).parents[1]
    path = root / "src/scenario_engine/reference_packs/ecommerce_evidence.py"
    source = path.read_text()
    ast.parse(source)
    assert "ecommerce_registry()" in source
    assert "DomainPackRegistry((pack,)).validate_plugins(pack, registry)" in source
    assert "domain_pack_versions" not in source
    assert "run_domain_pack" not in source
    for forbidden in (
        "requests", "urllib", "socket", "subprocess", "entry_points", "pkgutil",
        "os.environ", "getenv", "datetime.now", "time.time", "random", "secrets",
    ):
        assert forbidden not in source
    assert "fixture" not in source.lower()

