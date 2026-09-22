"""Closed, non-destructive execution of Phase 3.5 lossless wrapper plans."""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
from typing import Any, Mapping

from .compatibility import (
    MAX_MIGRATION_STEPS,
    ArtifactDescriptor,
    MigrationDisposition,
    MigrationPlan,
)
from .errors import (
    EvidenceMigrationContractError,
    EvidenceMigrationSourceIntegrityError,
)
from .export import _destination, export_evidence_bundle
from .models import (
    MAX_ARTIFACT_BYTES,
    EvidenceBundle,
    EvidenceEntry,
    EvidenceProvenance,
    EvidenceType,
)


_CHUNK_BYTES = 64 * 1024
_TARGET_CONTRACT = "evidence.bundle/1"
_EXECUTABLE_TRANSFORMATIONS: Mapping[str, tuple[str, str, EvidenceType]] = {
    "wrap-v1-manifest-as-evidence/1": ("manifest", "scenario.manifest/1", EvidenceType.MANIFEST),
    "wrap-v1-result-as-evidence/1": ("result", "scenario.result/1", EvidenceType.RESULT),
    "wrap-v2-batch-as-evidence/1": ("batch", "suite.batch/1", EvidenceType.MANIFEST),
    "wrap-v2-composition-as-evidence/1": ("composition", "composition.modules/1", EvidenceType.MANIFEST),
    "wrap-v2-matrix-as-evidence/1": ("matrix", "suite.matrix/1", EvidenceType.MANIFEST),
    "wrap-v2-suite-as-evidence/1": ("suite", "suite.manifest/1", EvidenceType.MANIFEST),
}


@dataclass(frozen=True, slots=True)
class MigrationExecutionResult:
    """Small immutable proof of one deterministic lossless execution."""

    plan_id: str
    source: ArtifactDescriptor
    target_contract: str
    source_sha256: str
    target_sha256: str
    transformations: tuple[str, ...]
    lossless: bool = True
    execution_id: str = ""

    def __post_init__(self) -> None:
        if self.lossless is not True:
            raise EvidenceMigrationContractError("migration result must be lossless")
        expected = hashlib.sha256(_result_bytes(self, omit_identity=True)).hexdigest()
        if self.execution_id and self.execution_id != expected:
            raise EvidenceMigrationContractError("migration execution identity does not match")
        object.__setattr__(self, "execution_id", expected)


def canonical_migration_result_bytes(result: MigrationExecutionResult) -> bytes:
    """Return canonical bytes for deterministic result comparison and identity."""
    if not isinstance(result, MigrationExecutionResult):
        raise EvidenceMigrationContractError("result must be a MigrationExecutionResult")
    return _result_bytes(result)


def execute_lossless_migration(
    plan: MigrationPlan,
    *,
    source_descriptor: ArtifactDescriptor,
    source_path: str | os.PathLike[str],
    destination: str | os.PathLike[str],
) -> MigrationExecutionResult:
    """Execute an approved wrapper route into a fresh evidence bundle directory."""
    transformation, evidence_type = _validate_plan(plan, source_descriptor)
    source = _regular_absolute_source(source_path)
    target = _absolute_absent_destination(destination)
    parent = target.parent
    scratch: Path | None = Path(tempfile.mkdtemp(prefix=f".{target.name}.migration-", dir=parent))
    try:
        copied = scratch / "source.json"
        source_hash, size = _verified_copy(source, copied, plan.source.source_sha256)
        entry = EvidenceEntry(
            logical_id=f"source-{source_hash}",
            evidence_type=evidence_type,
            artifact_schema=plan.source.schema_version,
            media_type="application/json",
            path="artifacts/source.json",
            sha256=source_hash,
            size_bytes=size,
            provenance=EvidenceProvenance(source_hash, transformation),
        )
        source_root = scratch / "root"
        (source_root / "artifacts").mkdir(parents=True)
        os.rename(copied, source_root / entry.path)
        bundle = EvidenceBundle((entry,))
        export_evidence_bundle(bundle, source_root=source_root, destination=target)
        result = MigrationExecutionResult(
            plan.plan_id,
            source_descriptor,
            plan.target_contract,
            source_hash,
            bundle.bundle_id,
            (transformation,),
        )
        return result
    finally:
        if scratch is not None:
            shutil.rmtree(scratch, ignore_errors=True)


def _validate_plan(
    plan: MigrationPlan, source: ArtifactDescriptor,
) -> tuple[str, EvidenceType]:
    if not isinstance(plan, MigrationPlan) or not isinstance(source, ArtifactDescriptor):
        raise EvidenceMigrationContractError("plan and source_descriptor must use accepted models")
    if plan.source != source:
        raise EvidenceMigrationContractError("plan source does not match supplied source descriptor")
    if plan.disposition is not MigrationDisposition.PLANNED:
        raise EvidenceMigrationContractError("migration plan disposition must be planned")
    steps = tuple(plan.steps)
    if not steps or len(steps) > MAX_MIGRATION_STEPS:
        raise EvidenceMigrationContractError("migration plan has an invalid step count")
    if any(step.lossless is not True for step in steps):
        raise EvidenceMigrationContractError("every migration step must be lossless")
    if steps[0].source_contract != source.schema_version:
        raise EvidenceMigrationContractError("migration source contract does not match descriptor")
    if steps[-1].target_contract != plan.target_contract or plan.target_contract != _TARGET_CONTRACT:
        raise EvidenceMigrationContractError("migration target contract is not exact")
    if any(left.target_contract != right.source_contract for left, right in zip(steps, steps[1:])):
        raise EvidenceMigrationContractError("migration step chain is not contiguous")
    contracts = (steps[0].source_contract,) + tuple(step.target_contract for step in steps)
    if len(contracts) != len(set(contracts)):
        raise EvidenceMigrationContractError("migration step chain contains a cycle")
    if len(steps) != 1:
        raise EvidenceMigrationContractError("no approved executable multi-step route exists")
    step = steps[0]
    route = _EXECUTABLE_TRANSFORMATIONS.get(step.transformation_id)
    if route is None:
        raise EvidenceMigrationContractError("unknown or unsupported migration transformation")
    kind, contract, evidence_type = route
    if (source.artifact_kind, source.schema_version, step.source_contract, step.target_contract) != (
        kind, contract, contract, _TARGET_CONTRACT,
    ):
        raise EvidenceMigrationContractError("transformation does not match its frozen route")
    return step.transformation_id, evidence_type


def _regular_absolute_source(value: str | os.PathLike[str]) -> Path:
    try:
        path = Path(value)
        if not path.is_absolute():
            raise ValueError
        metadata = path.lstat()
    except (OSError, TypeError, ValueError):
        raise EvidenceMigrationSourceIntegrityError("source must be an explicit readable absolute path") from None
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise EvidenceMigrationSourceIntegrityError("source must be a safe regular file")
    if metadata.st_size > MAX_ARTIFACT_BYTES:
        raise EvidenceMigrationSourceIntegrityError("source exceeds the artifact byte ceiling")
    return path


def _absolute_absent_destination(value: str | os.PathLike[str]) -> Path:
    try:
        path, _ = _destination(value)
    except Exception:
        raise EvidenceMigrationContractError("destination is invalid") from None
    return path


def _verified_copy(source: Path, output: Path, declared_hash: str | None) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    try:
        with source.open("rb") as reader, output.open("xb") as writer:
            while True:
                chunk = reader.read(_CHUNK_BYTES)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_ARTIFACT_BYTES:
                    raise EvidenceMigrationSourceIntegrityError("source exceeds the artifact byte ceiling")
                digest.update(chunk)
                writer.write(chunk)
            writer.flush()
            os.fsync(writer.fileno())
    except EvidenceMigrationSourceIntegrityError:
        raise
    except OSError:
        raise EvidenceMigrationSourceIntegrityError("source could not be copied safely") from None
    actual = digest.hexdigest()
    if declared_hash is not None and actual != declared_hash:
        raise EvidenceMigrationSourceIntegrityError("source SHA-256 does not match descriptor")
    return actual, total


def _jsonable(value: Any, *, omit_identity: bool = False) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {field.name: _jsonable(getattr(value, field.name), omit_identity=omit_identity)
                for field in fields(value) if not (omit_identity and field.name == "execution_id")}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item, omit_identity=omit_identity) for item in value]
    raise EvidenceMigrationContractError("migration result contains an unsupported value")


def _result_bytes(result: MigrationExecutionResult, *, omit_identity: bool = False) -> bytes:
    return json.dumps(_jsonable(result, omit_identity=omit_identity), ensure_ascii=False,
                      allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
