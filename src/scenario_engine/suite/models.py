"""Immutable, versioned data contracts for future suite orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import re
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from scenario_engine.manifest import ReproducibilityManifest
from scenario_engine.values import normalize

from .errors import SuiteContractError, UnsupportedReplayContractError


RUN_SCHEMA_VERSION = "suite.run/1"
SUITE_SCHEMA_VERSION = "suite.manifest/1"
MATRIX_SCHEMA_VERSION = "suite.matrix/1"
BATCH_SCHEMA_VERSION = "suite.batch/1"
READ_SCHEMA_VERSION = "suite.artifact-read/1"
MATRIX_CONTRACT_VERSION = "matrix.case/1"
BATCH_CONTRACT_VERSION = "batch.plan/1"
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_IDENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@/-]{0,255}\Z")


def _identity(value: Any, name: str) -> str:
    if not isinstance(value, str) or _IDENTITY.fullmatch(value) is None:
        raise SuiteContractError(f"{name} must be a non-empty portable identity")
    return value


def _hash(value: Any, name: str, *, optional: bool = False) -> str | None:
    if optional and value is None:
        return None
    if not isinstance(value, str) or _HASH.fullmatch(value) is None:
        raise SuiteContractError(f"{name} must be a lowercase SHA-256 hexadecimal string")
    return value


def _integer(value: Any, name: str, *, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SuiteContractError(f"{name} must be a nonnegative integer")
    if maximum is not None and value > maximum:
        raise SuiteContractError(f"{name} exceeds {maximum}")
    return value


def _strings(value: Mapping[str, str], name: str) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        raise SuiteContractError(f"{name} must be a mapping")
    result: dict[str, str] = {}
    for key, item in value.items():
        _identity(key, f"{name} key")
        if not isinstance(item, str) or not item:
            raise SuiteContractError(f"{name} values must be non-empty strings")
        result[key] = item
    return MappingProxyType({key: result[key] for key in sorted(result)})


def _semantic_mapping(value: Mapping[str, Any], name: str, *, ordered: bool = False) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise SuiteContractError(f"{name} must be a string-keyed mapping")
    try:
        normalized = normalize(value)
    except (TypeError, ValueError) as exc:
        raise SuiteContractError(f"{name} contains an invalid semantic value") from None
    # normalize validates recursively; retain semantic objects and isolate all containers.
    keys = tuple(value) if ordered else tuple(sorted(value))
    if len(keys) != len(normalized):
        raise SuiteContractError(f"{name} contains duplicate keys")
    return MappingProxyType({key: _freeze(value[key]) for key in keys})


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(value[key]) for key in sorted(value)})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


class ArtifactOrigin(str, Enum):
    V1_MANIFEST = "v1_manifest"
    V1_RESULT = "v1_result"


class ReadSupport(str, Enum):
    READABLE = "readable"


class ExecutionReplaySupport(str, Enum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"


class BatchStatus(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    NOT_RUN = "not_run"


@dataclass(frozen=True, slots=True)
class ArtifactReference:
    kind: str
    identity: str
    sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _identity(self.kind, "kind"))
        object.__setattr__(self, "identity", _identity(self.identity, "identity"))
        object.__setattr__(self, "sha256", _hash(self.sha256, "sha256"))


@dataclass(frozen=True, slots=True)
class DomainPackRecord:
    identity: str
    version: str
    content_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "identity", _identity(self.identity, "domain pack identity"))
        if not isinstance(self.version, str) or not self.version:
            raise SuiteContractError("domain pack version must be non-empty")
        object.__setattr__(self, "content_hash", _hash(self.content_hash, "content_hash"))


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    root_seed: str | int
    run_index: int
    locale: str
    reference_clock_start: datetime

    def __post_init__(self) -> None:
        if isinstance(self.root_seed, bool) or not isinstance(self.root_seed, (str, int)):
            raise SuiteContractError("root_seed must be a string or integer")
        object.__setattr__(self, "run_index", _integer(self.run_index, "run_index"))
        if not isinstance(self.locale, str) or not self.locale:
            raise SuiteContractError("locale must be a non-empty explicit string")
        if not isinstance(self.reference_clock_start, datetime):
            raise SuiteContractError("reference_clock_start must be a datetime")
        if self.reference_clock_start.tzinfo is None or self.reference_clock_start.utcoffset() is None:
            raise SuiteContractError("reference_clock_start must be timezone-aware")
        object.__setattr__(self, "reference_clock_start", self.reference_clock_start.astimezone(timezone.utc))


@dataclass(frozen=True, slots=True)
class CompatibilityRecord:
    execution_contract: str
    execution_replay: ExecutionReplaySupport
    plugin_versions: Mapping[str, str] = field(default_factory=dict)
    domain_packs: tuple[DomainPackRecord, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "execution_contract", _identity(self.execution_contract, "execution_contract"))
        if not isinstance(self.execution_replay, ExecutionReplaySupport):
            raise SuiteContractError("execution_replay must be an ExecutionReplaySupport")
        object.__setattr__(self, "plugin_versions", _strings(self.plugin_versions, "plugin_versions"))
        packs = tuple(self.domain_packs)
        if not all(isinstance(item, DomainPackRecord) for item in packs):
            raise SuiteContractError("domain_packs must contain DomainPackRecord values")
        identities = [item.identity for item in packs]
        if len(set(identities)) != len(identities):
            raise SuiteContractError("domain_packs contains a duplicate identity")
        object.__setattr__(self, "domain_packs", tuple(sorted(packs, key=lambda item: item.identity)))

    def require_execution_replay(self) -> None:
        if self.execution_replay is ExecutionReplaySupport.UNSUPPORTED:
            raise UnsupportedReplayContractError(self.execution_contract, ())


@dataclass(frozen=True, slots=True)
class RunManifestEnvelope:
    root_scenario_identity: str
    execution_context: ExecutionContext
    compatibility: CompatibilityRecord
    child_manifest: ReproducibilityManifest | None = None
    child_manifest_reference: ArtifactReference | None = None
    suite_hash: str | None = None
    schema_version: str = RUN_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != RUN_SCHEMA_VERSION:
            raise SuiteContractError(f"unsupported run schema version: {self.schema_version}")
        object.__setattr__(self, "root_scenario_identity", _identity(self.root_scenario_identity, "root_scenario_identity"))
        object.__setattr__(self, "suite_hash", _hash(self.suite_hash, "suite_hash", optional=True))
        if not isinstance(self.execution_context, ExecutionContext) or not isinstance(self.compatibility, CompatibilityRecord):
            raise SuiteContractError("execution_context and compatibility have invalid types")
        if (self.child_manifest is None) == (self.child_manifest_reference is None):
            raise SuiteContractError("exactly one child manifest or child manifest reference is required")
        if self.child_manifest is not None and not isinstance(self.child_manifest, ReproducibilityManifest):
            raise SuiteContractError("child_manifest must be a ReproducibilityManifest")


@dataclass(frozen=True, slots=True)
class SuiteManifest:
    root_scenario_identity: str
    composed_hash: str | None
    composition_contract_version: str | None
    module_hashes: Mapping[str, str] = field(default_factory=dict)
    domain_packs: tuple[DomainPackRecord, ...] = ()
    child_runs: tuple[ArtifactReference, ...] = ()
    schema_version: str = SUITE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SUITE_SCHEMA_VERSION:
            raise SuiteContractError(f"unsupported suite schema version: {self.schema_version}")
        object.__setattr__(self, "root_scenario_identity", _identity(self.root_scenario_identity, "root_scenario_identity"))
        object.__setattr__(self, "composed_hash", _hash(self.composed_hash, "composed_hash", optional=True))
        if (self.composed_hash is None) != (self.composition_contract_version is None):
            raise SuiteContractError("composed_hash and composition_contract_version must be present together")
        if self.composition_contract_version is not None:
            _identity(self.composition_contract_version, "composition_contract_version")
        modules = _strings(self.module_hashes, "module_hashes")
        for value in modules.values():
            _hash(value, "module content hash")
        object.__setattr__(self, "module_hashes", modules)
        object.__setattr__(self, "domain_packs", _unique_records(self.domain_packs, DomainPackRecord, "domain_packs"))
        object.__setattr__(self, "child_runs", _unique_references(self.child_runs, "child_runs"))


@dataclass(frozen=True, slots=True)
class BoundsMetadata:
    limit: int
    retained: int
    original: int

    def __post_init__(self) -> None:
        for name in ("limit", "retained", "original"):
            object.__setattr__(self, name, _integer(getattr(self, name), name))
        if self.retained > self.original or self.original > self.limit:
            raise SuiteContractError("bounds require retained <= original <= limit")


@dataclass(frozen=True, slots=True)
class MatrixCase:
    case_index: int
    case_id: str
    assignment: Mapping[str, Any]
    replay_identity: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "case_index", _integer(self.case_index, "case_index"))
        object.__setattr__(self, "case_id", _identity(self.case_id, "case_id"))
        object.__setattr__(self, "replay_identity", _identity(self.replay_identity, "replay_identity"))
        object.__setattr__(self, "assignment", _semantic_mapping(self.assignment, "assignment", ordered=True))


@dataclass(frozen=True, slots=True)
class MatrixCaseResultEnvelope:
    case: MatrixCase
    child_manifest: ArtifactReference
    child_result: ArtifactReference | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.case, MatrixCase) or not isinstance(self.child_manifest, ArtifactReference):
            raise SuiteContractError("matrix child relationship has invalid types")
        if self.child_result is not None and not isinstance(self.child_result, ArtifactReference):
            raise SuiteContractError("child_result must be an ArtifactReference")


@dataclass(frozen=True, slots=True)
class MatrixManifest:
    suite_identity: str
    suite_hash: str
    execution_context: ExecutionContext
    bounds: BoundsMetadata
    cases: tuple[MatrixCaseResultEnvelope, ...] = ()
    contract_version: str = MATRIX_CONTRACT_VERSION
    schema_version: str = MATRIX_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != MATRIX_SCHEMA_VERSION or self.contract_version != MATRIX_CONTRACT_VERSION:
            raise SuiteContractError("unsupported matrix contract version")
        object.__setattr__(self, "suite_identity", _identity(self.suite_identity, "suite_identity"))
        object.__setattr__(self, "suite_hash", _hash(self.suite_hash, "suite_hash"))
        cases = tuple(self.cases)
        if not all(isinstance(item, MatrixCaseResultEnvelope) for item in cases):
            raise SuiteContractError("cases must contain MatrixCaseResultEnvelope values")
        indexes = [item.case.case_index for item in cases]
        ids = [item.case.case_id for item in cases]
        if indexes != sorted(indexes) or len(set(indexes)) != len(indexes) or len(set(ids)) != len(ids):
            raise SuiteContractError("matrix cases require unique retained case/index ordering")
        if len(cases) != self.bounds.retained:
            raise SuiteContractError("matrix retained bound does not match cases")
        object.__setattr__(self, "cases", cases)


@dataclass(frozen=True, slots=True)
class MatrixResultEnvelope:
    manifest: MatrixManifest
    result_references: tuple[ArtifactReference, ...]
    schema_version: str = MATRIX_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != MATRIX_SCHEMA_VERSION or not isinstance(self.manifest, MatrixManifest):
            raise SuiteContractError("invalid matrix result schema")
        object.__setattr__(self, "result_references", _unique_references(self.result_references, "result_references"))


@dataclass(frozen=True, slots=True)
class FailureRecord:
    family: str
    code: str
    message: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "family", _identity(self.family, "failure family"))
        object.__setattr__(self, "code", _identity(self.code, "failure code"))
        if not isinstance(self.message, str) or not self.message or len(self.message) > 4096:
            raise SuiteContractError("failure message must contain 1..4096 characters")


@dataclass(frozen=True, slots=True)
class BatchItemResult:
    run_identity: str
    child_identity: str
    status: BatchStatus
    child_manifest: ArtifactReference | None = None
    child_result: ArtifactReference | None = None
    failure: FailureRecord | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_identity", _identity(self.run_identity, "run_identity"))
        object.__setattr__(self, "child_identity", _identity(self.child_identity, "child_identity"))
        if not isinstance(self.status, BatchStatus):
            raise SuiteContractError("status must be a BatchStatus")
        if self.status is BatchStatus.SUCCESS:
            if self.child_manifest is None or self.child_result is None or self.failure is not None:
                raise SuiteContractError("successful batch item requires child references and no failure")
        elif self.status is BatchStatus.FAILURE:
            if self.failure is None or self.child_result is not None:
                raise SuiteContractError("failed batch item requires failure and no child result")
        elif self.failure is not None or self.child_manifest is not None or self.child_result is not None:
            raise SuiteContractError("not-run batch item cannot contain result, manifest, or failure")


@dataclass(frozen=True, slots=True)
class BatchManifest:
    plan_identity: str
    plan_hash: str
    bundle_identity: str
    items: tuple[BatchItemResult, ...]
    success_count: int
    failure_count: int
    not_run_count: int
    contract_version: str = BATCH_CONTRACT_VERSION
    schema_version: str = BATCH_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != BATCH_SCHEMA_VERSION or self.contract_version != BATCH_CONTRACT_VERSION:
            raise SuiteContractError("unsupported batch contract version")
        object.__setattr__(self, "plan_identity", _identity(self.plan_identity, "plan_identity"))
        object.__setattr__(self, "plan_hash", _hash(self.plan_hash, "plan_hash"))
        object.__setattr__(self, "bundle_identity", _identity(self.bundle_identity, "bundle_identity"))
        items = tuple(self.items)
        if not all(isinstance(item, BatchItemResult) for item in items):
            raise SuiteContractError("items must contain BatchItemResult values")
        identities = [item.run_identity for item in items]
        if len(set(identities)) != len(identities):
            raise SuiteContractError("batch items contain a duplicate run identity")
        expected = {
            BatchStatus.SUCCESS: self.success_count,
            BatchStatus.FAILURE: self.failure_count,
            BatchStatus.NOT_RUN: self.not_run_count,
        }
        for status, count in expected.items():
            _integer(count, f"{status.value}_count")
            if sum(item.status is status for item in items) != count:
                raise SuiteContractError(f"{status.value} summary count does not match items")
        object.__setattr__(self, "items", items)


@dataclass(frozen=True, slots=True)
class BatchResultEnvelope:
    manifest: BatchManifest
    schema_version: str = BATCH_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != BATCH_SCHEMA_VERSION or not isinstance(self.manifest, BatchManifest):
            raise SuiteContractError("invalid batch result schema")


@dataclass(frozen=True, slots=True)
class ArtifactReadModel:
    origin: ArtifactOrigin
    artifact_version: str
    payload: Mapping[str, Any]
    read_support: ReadSupport = ReadSupport.READABLE
    execution_replay: ExecutionReplaySupport = ExecutionReplaySupport.UNSUPPORTED
    schema_version: str = READ_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != READ_SCHEMA_VERSION:
            raise SuiteContractError("unsupported artifact read schema version")
        if not isinstance(self.origin, ArtifactOrigin) or not isinstance(self.read_support, ReadSupport):
            raise SuiteContractError("invalid artifact read classification")
        if not isinstance(self.execution_replay, ExecutionReplaySupport):
            raise SuiteContractError("invalid execution replay classification")
        if not isinstance(self.artifact_version, str) or not self.artifact_version:
            raise SuiteContractError("artifact_version must be non-empty")
        object.__setattr__(self, "payload", _semantic_mapping(self.payload, "payload"))

    def require_execution_replay(self) -> None:
        if self.execution_replay is ExecutionReplaySupport.UNSUPPORTED:
            raise UnsupportedReplayContractError(self.artifact_version, ())


def _unique_records(values: Sequence[Any], expected: type[Any], name: str) -> tuple[Any, ...]:
    result = tuple(values)
    if not all(isinstance(item, expected) for item in result):
        raise SuiteContractError(f"{name} contains invalid records")
    identities = [item.identity for item in result]
    if len(set(identities)) != len(identities):
        raise SuiteContractError(f"{name} contains a duplicate identity")
    return tuple(sorted(result, key=lambda item: item.identity))


def _unique_references(values: Sequence[ArtifactReference], name: str) -> tuple[ArtifactReference, ...]:
    result = tuple(values)
    if not all(isinstance(item, ArtifactReference) for item in result):
        raise SuiteContractError(f"{name} contains invalid references")
    identities = [(item.kind, item.identity) for item in result]
    if len(set(identities)) != len(identities):
        raise SuiteContractError(f"{name} contains a duplicate identity")
    return result
