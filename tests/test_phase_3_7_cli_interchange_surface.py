from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from scenario_engine.cli import CLIExitCode
from scenario_engine.evidence import (
    ArtifactDescriptor, EvidenceBundle, EvidenceEntry, EvidenceProvenance,
    EvidenceRelationship, EvidenceType, canonical_evidence_bytes,
    canonical_migration_plan_bytes, canonical_migration_result_bytes,
    plan_migration, read_evidence_bundle,
)


ROOT = Path(__file__).parents[1]
ROUTES = (
    ("result", "scenario.result/1", "1.0.0", "wrap-v1-result-as-evidence/1"),
    ("manifest", "scenario.manifest/1", "1.0.0", "wrap-v1-manifest-as-evidence/1"),
    ("suite", "suite.manifest/1", "2.0.0", "wrap-v2-suite-as-evidence/1"),
    ("composition", "composition.modules/1", "2.0.0", "wrap-v2-composition-as-evidence/1"),
    ("matrix", "suite.matrix/1", "2.0.0", "wrap-v2-matrix-as-evidence/1"),
    ("batch", "suite.batch/1", "2.0.0", "wrap-v2-batch-as-evidence/1"),
)


def invoke(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, "-m", "scenario_engine.cli", *args], cwd=ROOT,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        env={"PYTHONPATH": str(ROOT / "src")},
    )


def bundle(root: Path) -> EvidenceBundle:
    payloads = {"artifacts/a.json": b'{"a":1}', "artifacts/b.json": b'{"b":2}'}
    for relative, data in payloads.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    entries = tuple(EvidenceEntry(
        logical_id=name, evidence_type=EvidenceType.RESULT,
        artifact_schema="scenario.result/1", media_type="application/json",
        path=relative, sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data),
        provenance=EvidenceProvenance(hashlib.sha256(data).hexdigest(), "fixture/1"),
    ) for name, (relative, data) in zip(("a", "b"), payloads.items()))
    value = EvidenceBundle(entries, (EvidenceRelationship("a", "b", "precedes"),))
    (root / "bundle.json").write_bytes(canonical_evidence_bytes(value))
    return value


def migration_args(source: Path, destination: Path, kind: str, contract: str,
                   version: str, digest: str) -> tuple[str, ...]:
    return (
        str(source), str(destination), "--artifact-kind", kind,
        "--schema-version", contract, "--product-version", version,
        "--source-sha256", digest,
    )


def test_exact_additive_command_surface_help_and_entrypoint() -> None:
    result = invoke("--help")
    assert result.returncode == 0 and result.stderr == b""
    commands = ("validate", "run", "replay", "hash", "inspect", "explain",
                "diff", "matrix", "batch", "export", "verify", "migrate")
    positions = [result.stdout.index(command.encode()) for command in commands]
    assert positions == sorted(positions)
    assert invoke("unknown").returncode == CLIExitCode.USAGE
    assert 'scenario = "scenario_engine.cli:main"' in (ROOT / "pyproject.toml").read_text()


def test_export_valid_bundle_exact_repeatable_and_deterministic(tmp_path: Path) -> None:
    source = tmp_path / "source"
    expected = bundle(source)
    first, second = tmp_path / "one", tmp_path / "two"
    human = invoke("export", str(source), str(first))
    machine = invoke("--json", "export", str(source), str(second))
    assert human.returncode == machine.returncode == CLIExitCode.SUCCESS
    assert human.stderr == machine.stderr == b""
    assert human.stdout == (f"exported evidence bundle {expected.bundle_id} (2 entries, 1 relationships)\n").encode()
    assert json.loads(machine.stdout) == {
        "bundle_id": expected.bundle_id, "command": "export", "entry_count": 2,
        "relationship_count": 1, "schema": "evidence.bundle/1", "verified": True,
    }
    assert read_evidence_bundle(first / "bundle.json", bundle_root=first) == expected
    assert {p.relative_to(first): p.read_bytes() for p in first.rglob("*") if p.is_file()} == {
        p.relative_to(second): p.read_bytes() for p in second.rglob("*") if p.is_file()
    }


def test_export_failures_are_closed_and_leave_no_partial_output(tmp_path: Path) -> None:
    missing, destination = tmp_path / "missing", tmp_path / "destination"
    invalid = invoke("export", str(missing), str(destination))
    assert invalid.returncode == CLIExitCode.SECURITY_OR_BOUND
    assert invalid.stdout == b"" and b"Traceback" not in invalid.stderr
    source = tmp_path / "source"
    bundle(source)
    existing = tmp_path / "existing"
    existing.mkdir()
    rejected = invoke("export", str(source), str(existing))
    assert rejected.returncode == CLIExitCode.IO and rejected.stdout == b""
    (source / "artifacts/a.json").unlink()
    absent = tmp_path / "absent"
    unsafe = invoke("export", str(source), str(absent))
    assert unsafe.returncode == CLIExitCode.SECURITY_OR_BOUND and not absent.exists()


def test_verify_success_is_deterministic_read_only(tmp_path: Path) -> None:
    source = tmp_path / "source"
    expected = bundle(source)
    before = {p.relative_to(source): p.read_bytes() for p in source.rglob("*") if p.is_file()}
    first = invoke("--json", "verify", str(source))
    second = invoke("--json", "verify", str(source))
    human = invoke("verify", str(source))
    assert first.returncode == second.returncode == human.returncode == 0
    assert first.stdout == second.stdout
    assert json.loads(first.stdout)["bundle_id"] == expected.bundle_id
    assert human.stdout == (f"verified evidence bundle {expected.bundle_id} (2 entries, 1 relationships)\n").encode()
    assert before == {p.relative_to(source): p.read_bytes() for p in source.rglob("*") if p.is_file()}


@pytest.mark.parametrize("failure", ("invalid", "noncanonical", "missing", "size", "hash", "schema", "symlink"))
def test_verify_rejects_invalid_unsafe_or_changed_bundle(tmp_path: Path, failure: str) -> None:
    source = tmp_path / failure
    value = bundle(source)
    index = source / "bundle.json"
    if failure == "invalid":
        index.write_bytes(b"{")
    elif failure == "noncanonical":
        index.write_text(json.dumps(json.loads(index.read_bytes()), indent=2))
    elif failure == "missing":
        (source / value.entries[0].path).unlink()
    elif failure == "size":
        (source / value.entries[0].path).write_bytes(b"longer")
    elif failure == "hash":
        (source / value.entries[0].path).write_bytes(b'{"x":1}')
    elif failure == "schema":
        raw = json.loads(index.read_bytes())
        raw["schema_version"] = "evidence.bundle/999"
        index.write_text(json.dumps(raw, sort_keys=True, separators=(",", ":")))
    else:
        target = source / value.entries[0].path
        target.unlink()
        target.symlink_to(source / value.entries[1].path)
    result = invoke("--json", "verify", str(source))
    assert result.returncode in (CLIExitCode.VALIDATION, CLIExitCode.SECURITY_OR_BOUND)
    assert result.stdout == b"" and result.stderr.startswith(b"scenario: error: ")
    assert b"Traceback" not in result.stderr


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO unavailable")
def test_verify_rejects_special_file(tmp_path: Path) -> None:
    source = tmp_path / "special"
    value = bundle(source)
    target = source / value.entries[0].path
    target.unlink()
    os.mkfifo(target)
    result = invoke("verify", str(source))
    assert result.returncode == CLIExitCode.SECURITY_OR_BOUND and result.stdout == b""


@pytest.mark.parametrize(("kind", "contract", "version", "transformation"), ROUTES)
def test_migrate_all_frozen_routes_delegate_losslessly(
    tmp_path: Path, kind: str, contract: str, version: str, transformation: str,
) -> None:
    source = tmp_path / f"{kind}.json"
    source.write_bytes(b'{"opaque":true}')
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    destination = tmp_path / f"{kind}-bundle"
    args = migration_args(source, destination, kind, contract, version, digest)
    result = invoke("--json", "migrate", *args)
    descriptor = ArtifactDescriptor(kind, contract, version, digest)
    expected = plan_migration(descriptor)
    assert result.returncode == 0 and result.stderr == b""
    assert json.loads(result.stdout)["plan_id"] == expected.plan_id
    assert json.loads(result.stdout)["transformations"] == [transformation]
    assert (destination / "artifacts/source.json").read_bytes() == source.read_bytes()
    actual = read_evidence_bundle(destination / "bundle.json", bundle_root=destination)
    assert json.loads(result.stdout)["target_sha256"] == actual.bundle_id


def test_migrate_dry_run_and_failure_exit_mapping(tmp_path: Path) -> None:
    source = tmp_path / "source.json"
    source.write_bytes(b"{}")
    digest = hashlib.sha256(b"{}").hexdigest()
    destination = tmp_path / "destination"
    args = migration_args(source, destination, "suite", "suite.manifest/1", "2.0.0", digest)
    descriptor = ArtifactDescriptor("suite", "suite.manifest/1", "2.0.0", digest)
    dry = invoke("--json", "migrate", *args, "--dry-run")
    assert dry.returncode == 0 and dry.stdout == canonical_migration_plan_bytes(plan_migration(descriptor)) + b"\n"
    assert not destination.exists()
    mismatch = list(args)
    mismatch[-1] = "a" * 64
    bad_hash = invoke("migrate", *mismatch)
    assert bad_hash.returncode == CLIExitCode.VALIDATION and not destination.exists()
    unsupported = invoke("migrate", *migration_args(
        source, destination, "domain-pack", "domain-pack/1", "2.0.0", digest,
    ))
    assert unsupported.returncode == CLIExitCode.VALIDATION and not destination.exists()
    malformed = invoke("migrate", str(source), str(destination), "--artifact-kind", "suite")
    assert malformed.returncode == CLIExitCode.USAGE
    destination.mkdir()
    existing = invoke("migrate", *args)
    assert existing.returncode == CLIExitCode.VALIDATION


def test_migrate_human_and_json_are_stable(tmp_path: Path) -> None:
    source = tmp_path / "source.json"
    source.write_bytes(b"{}")
    digest = hashlib.sha256(b"{}").hexdigest()
    descriptor = ArtifactDescriptor("result", "scenario.result/1", "1.0.0", digest)
    plan = plan_migration(descriptor)
    first = invoke("migrate", *migration_args(
        source, tmp_path / "one", "result", "scenario.result/1", "1.0.0", digest,
    ))
    second = invoke("--json", "migrate", *migration_args(
        source, tmp_path / "two", "result", "scenario.result/1", "1.0.0", digest,
    ))
    assert first.stdout == (f"migrated losslessly {plan.plan_id} -> "
                            f"{json.loads(second.stdout)['target_sha256']} "
                            "(wrap-v1-result-as-evidence/1)\n").encode()
    assert second.stdout == canonical_migration_result_bytes(json_result(second, descriptor, plan)) + b"\n"


def json_result(process: subprocess.CompletedProcess[bytes], descriptor: ArtifactDescriptor, plan):
    from scenario_engine.evidence import MigrationExecutionResult
    raw = json.loads(process.stdout)
    return MigrationExecutionResult(
        plan.plan_id, descriptor, plan.target_contract, raw["source_sha256"],
        raw["target_sha256"], tuple(raw["transformations"]), execution_id=raw["execution_id"],
    )


def test_static_local_trust_boundary_and_exit_codes() -> None:
    tree = ast.parse((ROOT / "src/scenario_engine/cli/main.py").read_text())
    imported = set()
    forbidden_calls = {"publish_evidence_bundles", "run_scenario", "replay_scenario"}
    new_handlers = {"_export", "_verify", "_migrate"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported.isdisjoint({"socket", "subprocess", "importlib", "random", "secrets", "time", "urllib"})
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in new_handlers:
            calls = {item.func.id for item in ast.walk(node)
                     if isinstance(item, ast.Call) and isinstance(item.func, ast.Name)}
            assert calls.isdisjoint(forbidden_calls)
    assert {member.value for member in CLIExitCode} == set(range(9))
