from __future__ import annotations

import hashlib
from importlib.resources import files
import json
from pathlib import Path
import subprocess
import sys

from scenario_engine.cli import CLIExitCode
from scenario_engine.compatibility_fixtures import export_compatibility_fixtures


ROOT = Path(__file__).parents[1]
FROZEN = ROOT / "tests/fixtures/phase4_11"


def invoke(*arguments: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, "-m", "scenario_engine.cli", *arguments], cwd=ROOT,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        env={"PYTHONPATH": str(ROOT / "src")},
    )


def tree_bytes(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*") if path.is_file()}


def test_packaged_resources_exactly_equal_frozen_corpus_and_manifest_hashes() -> None:
    packaged = Path(str(files("scenario_engine").joinpath("data/compatibility/phase4_11")))
    assert tree_bytes(packaged) == tree_bytes(FROZEN)
    manifest = json.loads((packaged / "compatibility-fixtures.json").read_bytes())
    assert manifest["schema_version"] == "scenario.compatibility-fixtures/1"
    for item in (*manifest["fixtures"], *manifest["support_files"]):
        assert hashlib.sha256((packaged / item["path"]).read_bytes()).hexdigest() == item["sha256"]


def test_help_discovers_and_explains_frozen_fixture_export() -> None:
    top = invoke("--help")
    detail = invoke("compatibility-fixtures", "--help")
    assert top.returncode == detail.returncode == CLIExitCode.SUCCESS
    assert b"compatibility-fixtures" in top.stdout
    for phrase in (b"current", b"historical", b"synthetic", b"replay", b"inspect", b"migrate", b"frozen"):
        assert phrase in detail.stdout
    assert b"scenario compatibility-fixtures export --out /absolute/path" in detail.stdout


def test_export_is_exact_repeatable_nonmutating_and_rejects_unsafe_destinations(tmp_path: Path) -> None:
    before = tree_bytes(FROZEN)
    first, second = tmp_path / "first", tmp_path / "second"
    assert invoke("compatibility-fixtures", "export", "--out", str(first)).returncode == 0
    export_compatibility_fixtures(second)
    assert tree_bytes(first) == tree_bytes(second) == before
    assert tree_bytes(FROZEN) == before

    relative = invoke("--json", "compatibility-fixtures", "export", "--out", "relative")
    remote = invoke("--json", "compatibility-fixtures", "export", "--out", "https://example.invalid/out")
    existing = invoke("--json", "compatibility-fixtures", "export", "--out", str(first))
    assert relative.returncode == remote.returncode == CLIExitCode.SECURITY_OR_BOUND
    assert existing.returncode == CLIExitCode.IO
    assert json.loads(relative.stderr)["code"] == "PATH_NOT_ABSOLUTE"
    assert json.loads(remote.stderr)["code"] == "PATH_REMOTE_FORBIDDEN"
    assert json.loads(existing.stderr)["code"] == "DESTINATION_ALREADY_EXISTS"


def test_representative_replay_and_migration_use_only_exported_bundle(tmp_path: Path) -> None:
    bundle = export_compatibility_fixtures(tmp_path / "bundle")
    manifest = json.loads((bundle / "compatibility-fixtures.json").read_bytes())
    indexed = {item["id"]: item for item in manifest["fixtures"]}
    for fixture_id in ("current-2.1.2-suite-run-v1", "historical-2.0.0-suite-run-v1"):
        item = indexed[fixture_id]
        result = invoke("--json", "replay", str(bundle / item["path"]),
                        "--scenario", str(bundle / item["scenario_resource"]),
                        "--inputs", (bundle / item["inputs_resource"]).read_text())
        assert result.returncode == CLIExitCode.SUCCESS
    old = indexed["historical-1.0.0-result-v1"]
    unsupported = invoke("--json", "replay", str(bundle / old["path"]),
                         "--scenario", str(bundle / old["scenario_resource"]))
    assert unsupported.returncode == CLIExitCode.REPLAY_COMPATIBILITY
    assert json.loads(unsupported.stderr)["code"] == "ENGINE_VERSION_UNSUPPORTED"
    missing = invoke("--json", "replay", str(bundle / indexed["current-2.1.2-suite-run-v1"]["path"]),
                     "--scenario", str(bundle / "scenarios/compatibility_case.yaml"))
    assert json.loads(missing.stderr)["code"] == "REPLAY_DATA_INCOMPLETE"
    unknown = indexed["synthetic-unknown-engine-suite-run-v1"]
    closed = invoke("--json", "replay", str(bundle / unknown["path"]),
                    "--scenario", str(bundle / "scenarios/compatibility_case.yaml"),
                    "--inputs", '{"selected":7}')
    assert json.loads(closed.stderr)["code"] == "ENGINE_VERSION_UNSUPPORTED"
    migrated = invoke("--json", "migrate", str(bundle / old["path"]), str(tmp_path / "migrated"),
                      "--artifact-kind", "result", "--schema-version", "scenario.result/1",
                      "--product-version", "1.0.0", "--source-sha256", old["sha256"])
    assert migrated.returncode == CLIExitCode.SUCCESS
