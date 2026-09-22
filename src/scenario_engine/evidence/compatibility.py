"""Pure compatibility reporting and non-executing migration planning.

The finite tables in this module are metadata policy.  They never read an
artifact, discover code, invoke an adapter, or execute a migration.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from enum import Enum
import hashlib
import json
import re
from typing import Any, Iterable, Mapping, Sequence

from scenario_engine._version import ENGINE_VERSION

from .errors import EvidenceBoundError, EvidenceContractError
from .models import _contract, _identifier, _sha256


EVIDENCE_COMPATIBILITY_REPORT_SCHEMA_VERSION = "evidence.compatibility-report/1"
EVIDENCE_MIGRATION_PLAN_SCHEMA_VERSION = "evidence.migration-plan/1"
CURRENT_PRODUCT_CONTRACT = "scenario-engine/2"
MAX_MIGRATION_STEPS = 1_000
MAX_COMPATIBILITY_REQUIREMENTS = 64
MAX_COMPATIBILITY_TEXT_BYTES = 256

_VERSION = re.compile(r"[0-9]+(?:\.[0-9]+){0,2}\Z")


class CompatibilityCapability(str, Enum):
    READABLE = "READABLE"
    INSPECTABLE = "INSPECTABLE"
    DIFFABLE = "DIFFABLE"
    EXECUTABLE = "EXECUTABLE"
    REPLAYABLE = "REPLAYABLE"
    MIGRATABLE = "MIGRATABLE"
    UNSUPPORTED = "UNSUPPORTED"


class CapabilityDisposition(str, Enum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"


class CompatibilityRequirement(str, Enum):
    ENGINE_VERSION = "engine-version"
    DSL_VERSION = "dsl-version"
    SCENARIO_HASH = "scenario-hash"
    RESOURCE_HASHES = "resource-hashes"
    PLUGIN_CONTEXT = "plugin-context"
    DOMAIN_PACK_CONTEXT = "domain-pack-context"
    COMPOSITION_CONTEXT = "composition-context"
    MATRIX_CASE = "matrix-case"
    SOURCE_BYTES = "source-bytes"


class CompatibilityReason(str, Enum):
    SUPPORTED = "supported"
    UNSUPPORTED_SCHEMA = "unsupported-schema"
    UNKNOWN_VERSION = "unknown-version"
    MISSING_REQUIRED_COORDINATE = "missing-required-coordinate"
    COORDINATE_MISMATCH = "coordinate-mismatch"
    ENGINE_VERSION_MISMATCH = "engine-version-mismatch"
    DSL_VERSION_MISMATCH = "dsl-version-mismatch"
    EXECUTION_NOT_IMPLIED_BY_READABILITY = "execution-not-implied-by-readability"
    LEGACY_REPLAY_UNSUPPORTED = "legacy-replay-unsupported"
    BATCH_RECORD_NOT_EXECUTION_STATE = "batch-record-not-execution-state"
    ASSERTION_EXECUTION_NOT_IMPLIED = "assertion-execution-not-implied"
    CHILD_EXECUTION_NOT_IMPLIED = "child-execution-not-implied"
    NO_LOSSLESS_MIGRATION_PATH = "no-lossless-migration-path"


class MigrationDisposition(str, Enum):
    PLANNED = "planned"
    UNSUPPORTED = "unsupported"


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > MAX_COMPATIBILITY_TEXT_BYTES:
        raise EvidenceContractError(
            f"{name} must be a non-empty string of at most {MAX_COMPATIBILITY_TEXT_BYTES} UTF-8 bytes"
        )
    return value


def _optional_hash(value: object, name: str) -> str | None:
    if value is None:
        return None
    return _sha256(value, name)


@dataclass(frozen=True, slots=True)
class RequirementCoordinate:
    """One expected coordinate and the caller-supplied local value, if any."""

    requirement: CompatibilityRequirement
    expected: str
    actual: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.requirement, CompatibilityRequirement):
            raise EvidenceContractError("requirement must be a CompatibilityRequirement")
        object.__setattr__(self, "expected", _text(self.expected, "expected coordinate"))
        if self.actual is not None:
            object.__setattr__(self, "actual", _text(self.actual, "actual coordinate"))

    @property
    def satisfied(self) -> bool:
        return self.actual == self.expected


@dataclass(frozen=True, slots=True)
class ArtifactDescriptor:
    """Minimal immutable metadata describing one artifact compatibility subject."""

    artifact_kind: str
    schema_version: str
    product_version: str
    source_sha256: str | None = None
    coordinates: tuple[RequirementCoordinate, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifact_kind", _identifier(self.artifact_kind, "artifact_kind"))
        object.__setattr__(self, "schema_version", _contract(self.schema_version, "schema_version"))
        if not isinstance(self.product_version, str) or _VERSION.fullmatch(self.product_version) is None:
            raise EvidenceContractError("product_version must contain one to three numeric components")
        object.__setattr__(self, "source_sha256", _optional_hash(self.source_sha256, "source_sha256"))
        coordinates = tuple(self.coordinates)
        if len(coordinates) > MAX_COMPATIBILITY_REQUIREMENTS:
            raise EvidenceBoundError("coordinates exceeds the bounded requirement ceiling")
        if not all(isinstance(item, RequirementCoordinate) for item in coordinates):
            raise EvidenceContractError("coordinates must contain RequirementCoordinate values")
        names = [item.requirement for item in coordinates]
        if len(names) != len(set(names)):
            raise EvidenceContractError("coordinates contains a duplicate requirement")
        object.__setattr__(self, "coordinates", tuple(sorted(coordinates, key=lambda item: item.requirement.value)))


@dataclass(frozen=True, slots=True)
class CapabilityDetermination:
    capability: CompatibilityCapability
    disposition: CapabilityDisposition
    reason: CompatibilityReason
    requirements: tuple[RequirementCoordinate, ...] = ()

    def __post_init__(self) -> None:
        if self.capability is CompatibilityCapability.UNSUPPORTED:
            raise EvidenceContractError("UNSUPPORTED is an aggregate capability, not a determination row")
        if not isinstance(self.capability, CompatibilityCapability):
            raise EvidenceContractError("capability must be a CompatibilityCapability")
        if not isinstance(self.disposition, CapabilityDisposition):
            raise EvidenceContractError("disposition must be a CapabilityDisposition")
        if not isinstance(self.reason, CompatibilityReason):
            raise EvidenceContractError("reason must be a CompatibilityReason")
        requirements = tuple(self.requirements)
        if not all(isinstance(item, RequirementCoordinate) for item in requirements):
            raise EvidenceContractError("requirements must contain RequirementCoordinate values")
        if tuple(sorted(requirements, key=lambda item: item.requirement.value)) != requirements:
            raise EvidenceContractError("requirements must use deterministic requirement order")
        object.__setattr__(self, "requirements", requirements)


@dataclass(frozen=True, slots=True)
class MigrationStep:
    transformation_id: str
    source_contract: str
    target_contract: str
    lossless: bool
    preconditions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "transformation_id", _identifier(self.transformation_id, "transformation_id"))
        object.__setattr__(self, "source_contract", _contract(self.source_contract, "source_contract"))
        object.__setattr__(self, "target_contract", _contract(self.target_contract, "target_contract"))
        if self.lossless is not True:
            raise EvidenceContractError("Phase 3.5 migration steps must be declared lossless")
        preconditions = tuple(self.preconditions)
        if not all(isinstance(item, str) and item for item in preconditions):
            raise EvidenceContractError("preconditions must contain non-empty strings")
        if len(preconditions) != len(set(preconditions)):
            raise EvidenceContractError("preconditions contains a duplicate")
        object.__setattr__(self, "preconditions", tuple(sorted(preconditions)))


@dataclass(frozen=True, slots=True)
class MigrationPlan:
    source: ArtifactDescriptor
    target_contract: str
    disposition: MigrationDisposition
    reason: CompatibilityReason
    steps: tuple[MigrationStep, ...] = ()
    schema_version: str = EVIDENCE_MIGRATION_PLAN_SCHEMA_VERSION
    plan_id: str = field(init=False)

    def __post_init__(self) -> None:
        if self.schema_version != EVIDENCE_MIGRATION_PLAN_SCHEMA_VERSION:
            raise EvidenceContractError("unsupported migration plan schema version")
        if not isinstance(self.source, ArtifactDescriptor):
            raise EvidenceContractError("source must be an ArtifactDescriptor")
        object.__setattr__(self, "target_contract", _contract(self.target_contract, "target_contract"))
        if not isinstance(self.disposition, MigrationDisposition) or not isinstance(self.reason, CompatibilityReason):
            raise EvidenceContractError("invalid migration disposition or reason")
        steps = tuple(self.steps)
        if len(steps) > MAX_MIGRATION_STEPS:
            raise EvidenceBoundError(f"migration plan exceeds {MAX_MIGRATION_STEPS} steps")
        if not all(isinstance(item, MigrationStep) for item in steps):
            raise EvidenceContractError("steps must contain MigrationStep values")
        if self.disposition is MigrationDisposition.PLANNED:
            if not steps or self.reason is not CompatibilityReason.SUPPORTED:
                raise EvidenceContractError("planned migration requires lossless steps and supported reason")
            if steps[0].source_contract != self.source.schema_version or steps[-1].target_contract != self.target_contract:
                raise EvidenceContractError("migration route endpoints do not match the plan")
            for left, right in zip(steps, steps[1:]):
                if left.target_contract != right.source_contract:
                    raise EvidenceContractError("migration route must be contiguous")
            contracts = (steps[0].source_contract,) + tuple(item.target_contract for item in steps)
            if len(contracts) != len(set(contracts)):
                raise EvidenceContractError("migration route must be acyclic")
        elif steps or self.reason is not CompatibilityReason.NO_LOSSLESS_MIGRATION_PATH:
            raise EvidenceContractError("unsupported migration must have no steps and no-lossless-path reason")
        object.__setattr__(self, "steps", steps)
        object.__setattr__(self, "plan_id", hashlib.sha256(_canonical_bytes(self, omit={"plan_id"})).hexdigest())


@dataclass(frozen=True, slots=True)
class CompatibilityReport:
    source: ArtifactDescriptor
    consumer_contract: str
    determinations: tuple[CapabilityDetermination, ...]
    capabilities: tuple[CompatibilityCapability, ...]
    lossless_migration_known: bool
    migration_plan_id: str | None = None
    schema_version: str = EVIDENCE_COMPATIBILITY_REPORT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != EVIDENCE_COMPATIBILITY_REPORT_SCHEMA_VERSION:
            raise EvidenceContractError("unsupported compatibility report schema version")
        if not isinstance(self.source, ArtifactDescriptor):
            raise EvidenceContractError("source must be an ArtifactDescriptor")
        object.__setattr__(self, "consumer_contract", _contract(self.consumer_contract, "consumer_contract"))
        determinations = tuple(self.determinations)
        expected = tuple(capability for capability in CompatibilityCapability if capability is not CompatibilityCapability.UNSUPPORTED)
        if tuple(item.capability for item in determinations) != expected:
            raise EvidenceContractError("determinations must contain every positive capability in frozen order")
        supported = tuple(item.capability for item in determinations if item.disposition is CapabilityDisposition.SUPPORTED)
        capabilities = supported or (CompatibilityCapability.UNSUPPORTED,)
        if tuple(self.capabilities) != capabilities:
            raise EvidenceContractError("capabilities do not match determinations")
        if self.lossless_migration_known is not (CompatibilityCapability.MIGRATABLE in supported):
            raise EvidenceContractError("lossless_migration_known must match MIGRATABLE")
        object.__setattr__(self, "determinations", determinations)
        object.__setattr__(self, "capabilities", capabilities)
        object.__setattr__(self, "migration_plan_id", _optional_hash(self.migration_plan_id, "migration_plan_id"))


@dataclass(frozen=True, slots=True)
class _Rule:
    artifact_kind: str
    schema_version: str
    product_major: int
    readable: bool = True
    inspectable: bool = True
    diffable: bool = True
    executable_requirements: tuple[CompatibilityRequirement, ...] = ()
    replayable_requirements: tuple[CompatibilityRequirement, ...] = ()
    executable_reason: CompatibilityReason = CompatibilityReason.EXECUTION_NOT_IMPLIED_BY_READABILITY
    replayable_reason: CompatibilityReason = CompatibilityReason.EXECUTION_NOT_IMPLIED_BY_READABILITY


_CORE = (
    CompatibilityRequirement.ENGINE_VERSION,
    CompatibilityRequirement.DSL_VERSION,
    CompatibilityRequirement.SCENARIO_HASH,
    CompatibilityRequirement.SOURCE_BYTES,
)
_SUITE = _CORE + (CompatibilityRequirement.RESOURCE_HASHES, CompatibilityRequirement.COMPOSITION_CONTEXT)
_MATRIX = _SUITE + (CompatibilityRequirement.MATRIX_CASE,)
_PACK = (CompatibilityRequirement.DOMAIN_PACK_CONTEXT, CompatibilityRequirement.PLUGIN_CONTEXT)

_RULES = (
    _Rule("result", "scenario.result/1", 1, executable_reason=CompatibilityReason.LEGACY_REPLAY_UNSUPPORTED,
          replayable_reason=CompatibilityReason.LEGACY_REPLAY_UNSUPPORTED),
    _Rule("manifest", "scenario.manifest/1", 1, executable_reason=CompatibilityReason.LEGACY_REPLAY_UNSUPPORTED,
          replayable_reason=CompatibilityReason.LEGACY_REPLAY_UNSUPPORTED),
    _Rule("dsl", "scenario.dsl/1", 1,
          executable_requirements=(CompatibilityRequirement.ENGINE_VERSION, CompatibilityRequirement.DSL_VERSION,
                                   CompatibilityRequirement.SOURCE_BYTES),
          replayable_requirements=_CORE),
    _Rule("result", "scenario.result/1", 2, executable_requirements=_CORE, replayable_requirements=_CORE),
    _Rule("manifest", "scenario.manifest/1", 2, executable_requirements=_CORE, replayable_requirements=_CORE),
    _Rule("suite", "suite.manifest/1", 2, executable_requirements=_SUITE, replayable_requirements=_SUITE),
    _Rule("composition", "composition.modules/1", 2, executable_requirements=_SUITE,
          replayable_requirements=_SUITE),
    _Rule("matrix", "suite.matrix/1", 2, executable_requirements=_MATRIX, replayable_requirements=_MATRIX),
    _Rule("batch", "suite.batch/1", 2,
          executable_reason=CompatibilityReason.BATCH_RECORD_NOT_EXECUTION_STATE,
          replayable_reason=CompatibilityReason.CHILD_EXECUTION_NOT_IMPLIED),
    _Rule("domain-pack", "domain-pack/1", 2, executable_requirements=_PACK, replayable_requirements=_PACK),
    _Rule("oracle-assertion", "oracle.assertion/1", 2,
          executable_reason=CompatibilityReason.ASSERTION_EXECUTION_NOT_IMPLIED,
          replayable_reason=CompatibilityReason.ASSERTION_EXECUTION_NOT_IMPLIED),
    _Rule("oracle-evaluation", "oracle.evaluation/1", 2,
          executable_reason=CompatibilityReason.ASSERTION_EXECUTION_NOT_IMPLIED,
          replayable_reason=CompatibilityReason.ASSERTION_EXECUTION_NOT_IMPLIED),
    _Rule("evidence-bundle", "evidence.bundle/1", 3,
          executable_reason=CompatibilityReason.CHILD_EXECUTION_NOT_IMPLIED,
          replayable_reason=CompatibilityReason.CHILD_EXECUTION_NOT_IMPLIED),
    _Rule("evidence-adapter-capability", "evidence.adapter-capability/1", 3),
    _Rule("evidence-adapter-receipt", "evidence.adapter-receipt/1", 3),
    _Rule("evidence-compatibility-report", EVIDENCE_COMPATIBILITY_REPORT_SCHEMA_VERSION, 3),
    _Rule("evidence-migration-plan", EVIDENCE_MIGRATION_PLAN_SCHEMA_VERSION, 3),
)


def _wrapper_step(source_contract: str, transformation: str) -> MigrationStep:
    return MigrationStep(
        transformation, source_contract, "evidence.bundle/1", True,
        ("preserve-source-bytes", "preserve-source-sha256"),
    )


_ROUTES: Mapping[tuple[str, str, int, str], tuple[tuple[MigrationStep, ...], ...]] = {
    ("result", "scenario.result/1", 1, "evidence.bundle/1"): (
        (_wrapper_step("scenario.result/1", "wrap-v1-result-as-evidence/1"),),
    ),
    ("manifest", "scenario.manifest/1", 1, "evidence.bundle/1"): (
        (_wrapper_step("scenario.manifest/1", "wrap-v1-manifest-as-evidence/1"),),
    ),
    ("suite", "suite.manifest/1", 2, "evidence.bundle/1"): (
        (_wrapper_step("suite.manifest/1", "wrap-v2-suite-as-evidence/1"),),
    ),
    ("composition", "composition.modules/1", 2, "evidence.bundle/1"): (
        (_wrapper_step("composition.modules/1", "wrap-v2-composition-as-evidence/1"),),
    ),
    ("matrix", "suite.matrix/1", 2, "evidence.bundle/1"): (
        (_wrapper_step("suite.matrix/1", "wrap-v2-matrix-as-evidence/1"),),
    ),
    ("batch", "suite.batch/1", 2, "evidence.bundle/1"): (
        (_wrapper_step("suite.batch/1", "wrap-v2-batch-as-evidence/1"),),
    ),
}


def _major(version: str) -> int:
    return int(version.split(".", 1)[0])


def _rule_for(source: ArtifactDescriptor) -> tuple[_Rule | None, CompatibilityReason]:
    major = _major(source.product_version)
    for rule in _RULES:
        if (rule.artifact_kind, rule.schema_version, rule.product_major) == (
            source.artifact_kind, source.schema_version, major,
        ):
            return rule, CompatibilityReason.SUPPORTED
    if any(rule.artifact_kind == source.artifact_kind and rule.schema_version == source.schema_version for rule in _RULES):
        return None, CompatibilityReason.UNKNOWN_VERSION
    return None, CompatibilityReason.UNSUPPORTED_SCHEMA


def _required(source: ArtifactDescriptor, names: tuple[CompatibilityRequirement, ...]) -> tuple[
    CapabilityDisposition, CompatibilityReason, tuple[RequirementCoordinate, ...]
]:
    values = {item.requirement: item for item in source.coordinates}
    requirements: list[RequirementCoordinate] = []
    for name in names:
        item = values.get(name)
        if item is None:
            expected = ENGINE_VERSION if name is CompatibilityRequirement.ENGINE_VERSION else "1" if name is CompatibilityRequirement.DSL_VERSION else "required"
            item = RequirementCoordinate(name, expected)
        requirements.append(item)
    ordered = tuple(sorted(requirements, key=lambda item: item.requirement.value))
    missing = next((item for item in ordered if item.actual is None), None)
    if missing is not None:
        return CapabilityDisposition.UNSUPPORTED, CompatibilityReason.MISSING_REQUIRED_COORDINATE, ordered
    mismatch = next((item for item in ordered if not item.satisfied), None)
    if mismatch is not None:
        reason = (CompatibilityReason.ENGINE_VERSION_MISMATCH
                  if mismatch.requirement is CompatibilityRequirement.ENGINE_VERSION
                  else CompatibilityReason.DSL_VERSION_MISMATCH
                  if mismatch.requirement is CompatibilityRequirement.DSL_VERSION
                  else CompatibilityReason.COORDINATE_MISMATCH)
        return CapabilityDisposition.UNSUPPORTED, reason, ordered
    return CapabilityDisposition.SUPPORTED, CompatibilityReason.SUPPORTED, ordered


def plan_migration(
    source: ArtifactDescriptor, target_contract: str = "evidence.bundle/1",
) -> MigrationPlan:
    """Return a deterministic plan; never execute or materialize its steps."""
    if not isinstance(source, ArtifactDescriptor):
        raise EvidenceContractError("source must be an ArtifactDescriptor")
    target = _contract(target_contract, "target_contract")
    routes = _ROUTES.get((source.artifact_kind, source.schema_version, _major(source.product_version), target), ())
    if not routes:
        return MigrationPlan(source, target, MigrationDisposition.UNSUPPORTED,
                             CompatibilityReason.NO_LOSSLESS_MIGRATION_PATH)
    valid = tuple(route for route in routes if route and len(route) <= MAX_MIGRATION_STEPS and all(step.lossless for step in route))
    if not valid:
        return MigrationPlan(source, target, MigrationDisposition.UNSUPPORTED,
                             CompatibilityReason.NO_LOSSLESS_MIGRATION_PATH)
    selected = min(valid, key=lambda route: (len(route), tuple(step.transformation_id for step in route)))
    return MigrationPlan(source, target, MigrationDisposition.PLANNED, CompatibilityReason.SUPPORTED, selected)


def compatibility_report(source: ArtifactDescriptor) -> CompatibilityReport:
    """Evaluate the frozen finite matrix using descriptor metadata only."""
    if not isinstance(source, ArtifactDescriptor):
        raise EvidenceContractError("source must be an ArtifactDescriptor")
    rule, absent_reason = _rule_for(source)
    plan = plan_migration(source)
    rows: list[CapabilityDetermination] = []
    for capability in CompatibilityCapability:
        if capability is CompatibilityCapability.UNSUPPORTED:
            continue
        if rule is None:
            disposition, reason, requirements = CapabilityDisposition.UNSUPPORTED, absent_reason, ()
        elif capability is CompatibilityCapability.READABLE:
            disposition, reason, requirements = CapabilityDisposition.SUPPORTED, CompatibilityReason.SUPPORTED, ()
        elif capability is CompatibilityCapability.INSPECTABLE:
            disposition, reason, requirements = CapabilityDisposition.SUPPORTED, CompatibilityReason.SUPPORTED, ()
        elif capability is CompatibilityCapability.DIFFABLE:
            disposition, reason, requirements = CapabilityDisposition.SUPPORTED, CompatibilityReason.SUPPORTED, ()
        elif capability is CompatibilityCapability.EXECUTABLE:
            if rule.executable_requirements:
                disposition, reason, requirements = _required(source, rule.executable_requirements)
            else:
                disposition, reason, requirements = CapabilityDisposition.UNSUPPORTED, rule.executable_reason, ()
        elif capability is CompatibilityCapability.REPLAYABLE:
            if rule.replayable_requirements:
                disposition, reason, requirements = _required(source, rule.replayable_requirements)
            else:
                disposition, reason, requirements = CapabilityDisposition.UNSUPPORTED, rule.replayable_reason, ()
        else:
            disposition = (CapabilityDisposition.SUPPORTED if plan.disposition is MigrationDisposition.PLANNED
                           else CapabilityDisposition.UNSUPPORTED)
            reason = (CompatibilityReason.SUPPORTED if disposition is CapabilityDisposition.SUPPORTED
                      else CompatibilityReason.NO_LOSSLESS_MIGRATION_PATH)
            requirements = ()
        rows.append(CapabilityDetermination(capability, disposition, reason, requirements))
    determinations = tuple(rows)
    supported = tuple(item.capability for item in determinations if item.disposition is CapabilityDisposition.SUPPORTED)
    return CompatibilityReport(
        source, CURRENT_PRODUCT_CONTRACT, determinations,
        supported or (CompatibilityCapability.UNSUPPORTED,),
        plan.disposition is MigrationDisposition.PLANNED,
        plan.plan_id if plan.disposition is MigrationDisposition.PLANNED else None,
    )


def _jsonable(value: Any, *, omit: set[str] | None = None) -> Any:
    omitted = omit or set()
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {item.name: _jsonable(getattr(value, item.name), omit=omitted)
                for item in fields(value) if item.name not in omitted}
    if isinstance(value, Mapping):
        return {key: _jsonable(value[key], omit=omitted) for key in sorted(value)}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item, omit=omitted) for item in value]
    raise EvidenceContractError("compatibility artifact contains an unsupported value")


def _canonical_bytes(value: object, *, omit: set[str] | None = None) -> bytes:
    return json.dumps(_jsonable(value, omit=omit), ensure_ascii=False, allow_nan=False,
                      sort_keys=True, separators=(",", ":")).encode("utf-8")


def canonical_compatibility_report_bytes(report: CompatibilityReport) -> bytes:
    if not isinstance(report, CompatibilityReport):
        raise EvidenceContractError("report must be a CompatibilityReport")
    return _canonical_bytes(report)


def compatibility_report_hash(report: CompatibilityReport) -> str:
    return hashlib.sha256(canonical_compatibility_report_bytes(report)).hexdigest()


def canonical_migration_plan_bytes(plan: MigrationPlan) -> bytes:
    if not isinstance(plan, MigrationPlan):
        raise EvidenceContractError("plan must be a MigrationPlan")
    return _canonical_bytes(plan, omit={"plan_id"})


def migration_plan_hash(plan: MigrationPlan) -> str:
    return hashlib.sha256(canonical_migration_plan_bytes(plan)).hexdigest()
