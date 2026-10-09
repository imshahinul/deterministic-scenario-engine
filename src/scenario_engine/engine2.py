"""Engine 2 manifest, result, execution, and exact replay evidence."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
import re
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .ids import ID_VERSION, LogicalID
from .manifest import GENERATOR_VERSIONS
from .rng import RNG_VERSION
from .schedule import (
    ENGINE2_EXECUTION_VERSION, MAX_REPLAY_SCHEDULER_SELECTIONS_VERIFIED,
    SCHEDULE_CONTRACT, ScheduleArtifact, exact_replay_internal,
)
from .scheduler import MAX_ACTORS, MAX_SCHEDULE_SEED, SCHEDULER_CONTRACT
from .values import MISSING, canonical_bytes, normalize


MANIFEST2_CONTRACT = "scenario.manifest/2"
RESULT2_CONTRACT = "scenario.result/2"
SUITE_RUN2_CONTRACT = "suite.run/2"
EXECUTION_MODEL = "logical-actors/1"
MAX_CANONICAL_RESULT_BYTES = 33_554_432
MAX_ENGINE2_NESTING_DEPTH = 32
MAX_SUITE2_MEMBERS = 10_000
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_ACTOR = re.compile(r"scenario:/actor/[^/]+\Z")


class Engine2EvidenceError(ValueError):
    """Stable fail-closed Engine 2 evidence error without value reflection."""

    code = "ENGINE2_EVIDENCE_INVALID"

    def __init__(self, field: str, message: str, *, code: str | None = None) -> None:
        self.field = field
        if code is not None:
            self.code = code
        super().__init__(f"{field}: {message}")


class Engine2EvidenceBoundError(Engine2EvidenceError):
    code = "ENGINE2_EVIDENCE_BOUND_EXCEEDED"


class Engine2ReplayMismatch(Engine2EvidenceError):
    code = "ENGINE2_REPLAY_MISMATCH"


def _hash(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _HASH.fullmatch(value) is None:
        raise Engine2EvidenceError(field_name, "must be 64 lowercase hexadecimal characters")
    return value


def _integer(value: object, field_name: str, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise Engine2EvidenceError(field_name, "must be a nonnegative integer excluding bool")
    if maximum is not None and value > maximum:
        raise Engine2EvidenceBoundError(field_name, f"exceeds inclusive maximum {maximum}")
    return value


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise Engine2EvidenceError(field_name, "must be a nonempty string")
    return value


def _strings(value: object, field_name: str) -> Mapping[str, str]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) and isinstance(item, str) for key, item in value.items()
    ):
        raise Engine2EvidenceError(field_name, "must map strings to strings")
    return MappingProxyType({key: value[key] for key in sorted(value)})


def _clock(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise Engine2EvidenceError(field_name, "must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _freeze(value: Any) -> Any:
    normalize(value)
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(value[key]) for key in sorted(value)})
    if isinstance(value, (tuple, list)):
        return tuple(_freeze(item) for item in value)
    return value


def _actor(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _ACTOR.fullmatch(value) is None:
        raise Engine2EvidenceError(field_name, "must be a canonical actor address")
    from .scheduler import SchedulerInput
    try:
        checked = SchedulerInput(
            "0" * 64, {}, 0, 0, 0, 0, datetime(1970, 1, 1, tzinfo=timezone.utc),
            (value,), (value,),
        ).declared_actors[0]
    except ValueError:
        raise Engine2EvidenceError(field_name, "must be a canonical actor address") from None
    if checked != value:
        raise Engine2EvidenceError(field_name, "must be a canonical actor address")
    return value


@dataclass(frozen=True, slots=True)
class Engine2Manifest:
    scenario_hash: str
    root_seed: str | int
    schedule_seed: int
    input_resource_hashes: Mapping[str, str]
    reference_clock_start: datetime
    run_index: int = 0
    domain_pack_versions: Mapping[str, str] = field(default_factory=dict)
    generator_versions: Mapping[str, str] = field(default_factory=lambda: GENERATOR_VERSIONS)
    rng_algorithm_version: str = RNG_VERSION
    id_algorithm_version: str = ID_VERSION
    locale: str = "C"
    execution_model: str = EXECUTION_MODEL
    engine_version: str = ENGINE2_EXECUTION_VERSION
    dsl_version: int = 2
    scheduler_contract: str = SCHEDULER_CONTRACT
    manifest_hash: str = ""
    contract: str = MANIFEST2_CONTRACT

    def __post_init__(self) -> None:
        if self.contract != MANIFEST2_CONTRACT or self.engine_version != ENGINE2_EXECUTION_VERSION:
            raise Engine2EvidenceError("manifest", "unsupported contract or engine version")
        if self.dsl_version != 2 or isinstance(self.dsl_version, bool):
            raise Engine2EvidenceError("dsl_version", "must be integer 2")
        if self.execution_model != EXECUTION_MODEL or self.scheduler_contract != SCHEDULER_CONTRACT:
            raise Engine2EvidenceError("manifest", "unsupported execution or scheduler contract")
        object.__setattr__(self, "scenario_hash", _hash(self.scenario_hash, "scenario_hash"))
        if isinstance(self.root_seed, bool) or not isinstance(self.root_seed, (str, int)):
            raise Engine2EvidenceError("root_seed", "must be a string or integer excluding bool")
        object.__setattr__(self, "schedule_seed", _integer(self.schedule_seed, "schedule_seed", MAX_SCHEDULE_SEED))
        object.__setattr__(self, "run_index", _integer(self.run_index, "run_index"))
        object.__setattr__(self, "reference_clock_start", _clock(self.reference_clock_start, "reference_clock_start"))
        for name in ("input_resource_hashes", "domain_pack_versions", "generator_versions"):
            object.__setattr__(self, name, _strings(getattr(self, name), name))
        if self.locale != "C" or self.rng_algorithm_version != RNG_VERSION or self.id_algorithm_version != ID_VERSION:
            raise Engine2EvidenceError("manifest", "unsupported locale or algorithm version")
        digest = hashlib.sha256(canonical_bytes(self.identity_payload())).hexdigest()
        if self.manifest_hash and _hash(self.manifest_hash, "manifest_hash") != digest:
            raise Engine2EvidenceError("manifest_hash", "does not match canonical manifest identity")
        object.__setattr__(self, "manifest_hash", digest)

    def identity_payload(self) -> Mapping[str, Any]:
        return {
            "contract": self.contract, "domain_pack_versions": self.domain_pack_versions,
            "dsl_version": self.dsl_version, "engine_version": self.engine_version,
            "execution_model": self.execution_model, "generator_versions": self.generator_versions,
            "id_algorithm_version": self.id_algorithm_version,
            "input_resource_hashes": self.input_resource_hashes, "locale": self.locale,
            "reference_clock_start": self.reference_clock_start,
            "rng_algorithm_version": self.rng_algorithm_version, "root_seed": self.root_seed,
            "run_index": self.run_index, "scenario_hash": self.scenario_hash,
            "schedule_seed": self.schedule_seed, "scheduler_contract": self.scheduler_contract,
        }

    def payload(self) -> Mapping[str, Any]:
        return {**self.identity_payload(), "manifest_hash": self.manifest_hash}


@dataclass(frozen=True, slots=True)
class ScheduleReference:
    schedule_hash: str
    scenario_hash: str
    contract: str = SCHEDULE_CONTRACT

    def __post_init__(self) -> None:
        if self.contract != SCHEDULE_CONTRACT:
            raise Engine2EvidenceError("schedule_reference.contract", "unsupported contract")
        object.__setattr__(self, "schedule_hash", _hash(self.schedule_hash, "schedule_reference.schedule_hash"))
        object.__setattr__(self, "scenario_hash", _hash(self.scenario_hash, "schedule_reference.scenario_hash"))

    def payload(self) -> Mapping[str, Any]:
        return {"contract": self.contract, "scenario_hash": self.scenario_hash,
                "schedule_hash": self.schedule_hash}


@dataclass(frozen=True, slots=True)
class ResultFailure:
    actor: str
    code: str
    selection_ordinal: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "actor", _actor(self.actor, "failure.actor"))
        _text(self.code, "failure.code")
        object.__setattr__(self, "selection_ordinal", _integer(
            self.selection_ordinal, "failure.selection_ordinal", MAX_REPLAY_SCHEDULER_SELECTIONS_VERIFIED - 1,
        ))

    def payload(self) -> Mapping[str, Any]:
        return {"actor": self.actor, "code": self.code, "selection_ordinal": self.selection_ordinal}


@dataclass(frozen=True, slots=True)
class Engine2Result:
    manifest: Engine2Manifest
    scenario_id: str
    schedule_reference: ScheduleReference
    classification: str
    failure: ResultFailure | None
    final_state: Mapping[str, Any]
    final_logical_clock: datetime
    history: tuple[Mapping[str, Any], ...]
    artifacts: tuple[Mapping[str, Any], ...]
    actors: tuple[Mapping[str, Any], ...]
    provenance: tuple[Mapping[str, Any], ...] = ()
    result_hash: str = ""
    contract: str = RESULT2_CONTRACT

    def __post_init__(self) -> None:
        if self.contract != RESULT2_CONTRACT or not isinstance(self.manifest, Engine2Manifest):
            raise Engine2EvidenceError("result", "unsupported contract or manifest")
        _text(self.scenario_id, "scenario_id")
        if not isinstance(self.schedule_reference, ScheduleReference):
            raise Engine2EvidenceError("schedule_reference", "must be ScheduleReference")
        if self.schedule_reference.scenario_hash != self.manifest.scenario_hash:
            raise Engine2EvidenceError("schedule_reference.scenario_hash", "does not match manifest")
        if self.classification == "SUCCESS":
            if self.failure is not None:
                raise Engine2EvidenceError("failure", "SUCCESS requires null failure")
        elif self.classification == "FAILED":
            if not isinstance(self.failure, ResultFailure):
                raise Engine2EvidenceError("failure", "FAILED requires ResultFailure")
        else:
            raise Engine2EvidenceError("classification", "must be SUCCESS or FAILED")
        object.__setattr__(self, "final_state", _freeze(self.final_state))
        object.__setattr__(self, "final_logical_clock", _clock(self.final_logical_clock, "final_logical_clock"))
        for name in ("history", "artifacts", "actors", "provenance"):
            values = tuple(getattr(self, name))
            if not all(isinstance(item, Mapping) for item in values):
                raise Engine2EvidenceError(name, "must contain mappings")
            object.__setattr__(self, name, tuple(_freeze(item) for item in values))
        if len(self.actors) > MAX_ACTORS:
            raise Engine2EvidenceBoundError("actors", f"exceeds inclusive maximum {MAX_ACTORS}")
        actor_names = tuple(item.get("actor") for item in self.actors)
        for name in actor_names:
            _actor(name, "actors.actor")
        if actor_names != tuple(sorted(actor_names, key=str.encode)) or len(actor_names) != len(set(actor_names)):
            raise Engine2EvidenceError("actors", "must be unique canonical actor order")
        digest = hashlib.sha256(canonical_bytes(self.identity_payload())).hexdigest()
        if self.result_hash and _hash(self.result_hash, "result_hash") != digest:
            raise Engine2EvidenceError("result_hash", "does not match canonical result identity")
        object.__setattr__(self, "result_hash", digest)
        if len(canonical_result2_bytes(self)) > MAX_CANONICAL_RESULT_BYTES:
            raise Engine2EvidenceBoundError("result", "exceeds MAX_CANONICAL_RESULT_BYTES")

    def identity_payload(self) -> Mapping[str, Any]:
        return {
            "actors": self.actors, "artifacts": self.artifacts,
            "classification": self.classification, "contract": self.contract,
            "failure": None if self.failure is None else self.failure.payload(),
            "final_logical_clock": self.final_logical_clock, "final_state": self.final_state,
            "history": self.history, "manifest": self.manifest.payload(),
            "provenance": self.provenance, "scenario_id": self.scenario_id,
            "schedule_reference": self.schedule_reference.payload(),
        }

    def payload(self) -> Mapping[str, Any]:
        return {**self.identity_payload(), "result_hash": self.result_hash}


def _history_payload(record: Any) -> Mapping[str, Any]:
    actor = _actor(record.address.semantic().split("/step/", 1)[0], "history.actor")
    return {
        "actor": actor, "address": record.address.semantic(),
        "artifacts": tuple((item_id, kind) for item_id, kind in record.emitted_artifacts),
        "faults_applied": tuple(record.faults_applied or ()), "patch": record.state_patch,
        "post": record.post_state_fingerprint, "pre": record.pre_state_fingerprint,
        "timestamp": record.logical_timestamp, "transition": record.transition_selected,
    }


def _artifact_payload(artifact: Any) -> Mapping[str, Any]:
    actor = _actor(artifact.address.semantic().split("/step/", 1)[0], "artifacts.actor")
    return {"actor": actor, "address": artifact.address.semantic(), "id": artifact.logical_id,
            "name": artifact.name, "type": artifact.artifact_type, "value": artifact.value}


def construct_result2(scenario: Any, outcome: Any) -> Engine2Result:
    """Snapshot truthful Engine 2 execution evidence from one completed internal outcome."""
    from .canonical import canonical_scenario_hash
    from .dsl.actor_runtime import ActorExecutionOutcome, _generator_versions
    if not isinstance(outcome, ActorExecutionOutcome) or not isinstance(outcome.schedule, ScheduleArtifact):
        raise Engine2EvidenceError("outcome", "must contain authoritative completed schedule evidence")
    schedule = outcome.schedule
    scenario_hash = canonical_scenario_hash(scenario)
    if schedule.scenario_hash != scenario_hash:
        raise Engine2EvidenceError("outcome.schedule", "does not match scenario")
    manifest = Engine2Manifest(
        scenario_hash, schedule.execution.root_seed, schedule.schedule_seed,
        schedule.input_resource_hashes, schedule.execution.reference_clock_start,
        schedule.run_index, generator_versions=_generator_versions(scenario.document),
    )
    failure = None if schedule.failure is None else ResultFailure(
        schedule.failure.actor, schedule.failure.code, schedule.failure.selection_ordinal,
    )
    return Engine2Result(
        manifest, scenario.scenario_id,
        ScheduleReference(schedule.schedule_hash, schedule.scenario_hash),
        outcome.classification, failure, outcome.final_state, outcome.final_logical_clock,
        tuple(_history_payload(item) for item in outcome.committed_history),
        tuple(_artifact_payload(item) for item in outcome.artifacts),
        tuple({"actor": item.actor_address, "next_step": item.next_step_address,
               "terminal": item.terminal} for item in outcome.actor_states), (),
    )


def canonical_manifest2_identity_bytes(manifest: Engine2Manifest) -> bytes:
    return canonical_bytes(manifest.identity_payload())


def canonical_manifest2_bytes(manifest: Engine2Manifest) -> bytes:
    return canonical_bytes(manifest.payload())


def canonical_result2_identity_bytes(result: Engine2Result) -> bytes:
    encoded = canonical_bytes(result.identity_payload())
    if len(encoded) > MAX_CANONICAL_RESULT_BYTES:
        raise Engine2EvidenceBoundError("result", "exceeds MAX_CANONICAL_RESULT_BYTES")
    return encoded


def canonical_result2_bytes(result: Engine2Result) -> bytes:
    encoded = canonical_bytes(result.payload())
    if len(encoded) > MAX_CANONICAL_RESULT_BYTES:
        raise Engine2EvidenceBoundError("result", "exceeds MAX_CANONICAL_RESULT_BYTES")
    return encoded


@dataclass(frozen=True, slots=True)
class SuiteRun2Member:
    result_hash: str
    manifest_hash: str
    schedule_hash: str
    result_contract: str = RESULT2_CONTRACT
    manifest_contract: str = MANIFEST2_CONTRACT
    schedule_contract: str = SCHEDULE_CONTRACT

    def __post_init__(self) -> None:
        if (self.result_contract, self.manifest_contract, self.schedule_contract) != (
            RESULT2_CONTRACT, MANIFEST2_CONTRACT, SCHEDULE_CONTRACT,
        ):
            raise Engine2EvidenceError("members", "contains an incompatible child contract")
        for name in ("result_hash", "manifest_hash", "schedule_hash"):
            object.__setattr__(self, name, _hash(getattr(self, name), f"members.{name}"))

    def payload(self) -> Mapping[str, Any]:
        return {"manifest_contract": self.manifest_contract, "manifest_hash": self.manifest_hash,
                "result_contract": self.result_contract, "result_hash": self.result_hash,
                "schedule_contract": self.schedule_contract, "schedule_hash": self.schedule_hash}


@dataclass(frozen=True, slots=True)
class SuiteRun2:
    members: tuple[SuiteRun2Member, ...]
    suite_hash: str = ""
    contract: str = SUITE_RUN2_CONTRACT

    def __post_init__(self) -> None:
        if self.contract != SUITE_RUN2_CONTRACT:
            raise Engine2EvidenceError("contract", "unsupported suite contract")
        members = tuple(self.members)
        if not members or len(members) > MAX_SUITE2_MEMBERS or not all(isinstance(item, SuiteRun2Member) for item in members):
            raise Engine2EvidenceBoundError("members", "must contain 1..10000 SuiteRun2Member values")
        ordered = tuple(sorted(members, key=lambda item: tuple(
            value.encode("utf-8") for value in (item.result_hash, item.manifest_hash, item.schedule_hash)
        )))
        if len({item.result_hash for item in ordered}) != len(ordered):
            raise Engine2EvidenceError("members", "contains a duplicate result identity")
        object.__setattr__(self, "members", ordered)
        digest = hashlib.sha256(canonical_bytes(self.identity_payload())).hexdigest()
        if self.suite_hash and _hash(self.suite_hash, "suite_hash") != digest:
            raise Engine2EvidenceError("suite_hash", "does not match canonical suite identity")
        object.__setattr__(self, "suite_hash", digest)
        if len(canonical_suite_run2_bytes(self)) > MAX_CANONICAL_RESULT_BYTES:
            raise Engine2EvidenceBoundError("suite", "exceeds MAX_CANONICAL_RESULT_BYTES")

    def identity_payload(self) -> Mapping[str, Any]:
        return {"contract": self.contract, "members": tuple(item.payload() for item in self.members)}

    def payload(self) -> Mapping[str, Any]:
        return {**self.identity_payload(), "suite_hash": self.suite_hash}


def canonical_suite_run2_bytes(suite: SuiteRun2) -> bytes:
    encoded = canonical_bytes(suite.payload())
    if len(encoded) > MAX_CANONICAL_RESULT_BYTES:
        raise Engine2EvidenceBoundError("suite", "exceeds MAX_CANONICAL_RESULT_BYTES")
    return encoded


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise Engine2EvidenceError("json", "contains a duplicate key")
        result[key] = value
    return result


def _depth(value: Any, level: int = 0) -> None:
    if level > MAX_ENGINE2_NESTING_DEPTH:
        raise Engine2EvidenceBoundError("json", "exceeds maximum nesting depth")
    if isinstance(value, Mapping):
        for item in value.values(): _depth(item, level + 1)
    elif isinstance(value, list):
        for item in value: _depth(item, level + 1)


def _exact(value: object, fields: set[str], name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise Engine2EvidenceError(name, "has missing or unknown fields")
    return value


def _semantic(value: Any) -> Any:
    if isinstance(value, list): return tuple(_semantic(item) for item in value)
    if not isinstance(value, Mapping): return value
    if "$type" not in value: return {key: _semantic(item) for key, item in value.items()}
    if value == {"$type": "missing"}: return MISSING
    item = _exact(value, {"$type", "value"}, "semantic value")
    kind, raw = item["$type"], item["value"]
    try:
        if kind == "datetime" and isinstance(raw, str):
            parsed = datetime.fromisoformat(raw)
            if parsed.tzinfo is None: raise ValueError
            return parsed
        if kind == "decimal" and isinstance(raw, str): return Decimal(raw)
        if kind == "logical-id" and isinstance(raw, str): return LogicalID(raw)
        if kind == "duration-microseconds" and isinstance(raw, int) and not isinstance(raw, bool):
            return timedelta(microseconds=raw)
    except (ValueError, ArithmeticError):
        pass
    raise Engine2EvidenceError("semantic value", "is malformed")


def _raw(source: bytes | str) -> tuple[bytes, Mapping[str, Any]]:
    if not isinstance(source, (bytes, str)): raise TypeError("source must be bytes or str")
    data = source if isinstance(source, bytes) else source.encode("utf-8")
    if len(data) > MAX_CANONICAL_RESULT_BYTES:
        raise Engine2EvidenceBoundError("evidence", "exceeds MAX_CANONICAL_RESULT_BYTES")
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_object,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except Engine2EvidenceError: raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError):
        raise Engine2EvidenceError("json", "must be strict UTF-8 JSON") from None
    _depth(value)
    if not isinstance(value, Mapping): raise Engine2EvidenceError("json", "root must be an object")
    return data, value


_MANIFEST_FIELDS = {"contract", "domain_pack_versions", "dsl_version", "engine_version",
    "execution_model", "generator_versions", "id_algorithm_version", "input_resource_hashes",
    "locale", "manifest_hash", "reference_clock_start", "rng_algorithm_version", "root_seed",
    "run_index", "scenario_hash", "schedule_seed", "scheduler_contract"}


def _manifest(raw: object) -> Engine2Manifest:
    value = _exact(raw, _MANIFEST_FIELDS, "manifest")
    decoded = {key: _semantic(item) for key, item in value.items()}
    return Engine2Manifest(
        decoded["scenario_hash"], decoded["root_seed"], decoded["schedule_seed"],
        decoded["input_resource_hashes"], decoded["reference_clock_start"], decoded["run_index"],
        decoded["domain_pack_versions"], decoded["generator_versions"],
        decoded["rng_algorithm_version"], decoded["id_algorithm_version"], decoded["locale"],
        decoded["execution_model"], decoded["engine_version"], decoded["dsl_version"],
        decoded["scheduler_contract"], decoded["manifest_hash"], decoded["contract"],
    )


def read_manifest2(source: bytes | str) -> Engine2Manifest:
    data, raw = _raw(source)
    result = _manifest(raw)
    if canonical_manifest2_bytes(result) != data:
        raise Engine2EvidenceError("manifest", "must be canonical JSON bytes")
    return result


def read_result2(source: bytes | str) -> Engine2Result:
    data, raw = _raw(source)
    value = _exact(raw, {"actors", "artifacts", "classification", "contract", "failure",
        "final_logical_clock", "final_state", "history", "manifest", "provenance", "result_hash",
        "scenario_id", "schedule_reference"}, "result")
    reference = _exact(value["schedule_reference"], {"contract", "scenario_hash", "schedule_hash"},
                       "schedule_reference")
    failure = None
    if value["failure"] is not None:
        item = _exact(value["failure"], {"actor", "code", "selection_ordinal"}, "failure")
        failure = ResultFailure(item["actor"], item["code"], item["selection_ordinal"])
    decoded = {key: _semantic(item) for key, item in value.items()
               if key not in {"manifest", "schedule_reference", "failure"}}
    result = Engine2Result(
        _manifest(value["manifest"]), decoded["scenario_id"],
        ScheduleReference(reference["schedule_hash"], reference["scenario_hash"], reference["contract"]),
        decoded["classification"], failure, decoded["final_state"], decoded["final_logical_clock"],
        decoded["history"], decoded["artifacts"], decoded["actors"], decoded["provenance"],
        decoded["result_hash"], decoded["contract"],
    )
    if canonical_result2_bytes(result) != data:
        raise Engine2EvidenceError("result", "must be canonical JSON bytes")
    return result


def read_suite_run2(source: bytes | str) -> SuiteRun2:
    data, raw = _raw(source)
    value = _exact(raw, {"contract", "members", "suite_hash"}, "suite")
    if not isinstance(value["members"], list) or len(value["members"]) > MAX_SUITE2_MEMBERS:
        raise Engine2EvidenceBoundError("members", "must be a bounded list")
    fields = {"manifest_contract", "manifest_hash", "result_contract", "result_hash",
              "schedule_contract", "schedule_hash"}
    members = []
    for index, raw_member in enumerate(value["members"]):
        item = _exact(raw_member, fields, f"members[{index}]")
        members.append(SuiteRun2Member(item["result_hash"], item["manifest_hash"], item["schedule_hash"],
            item["result_contract"], item["manifest_contract"], item["schedule_contract"]))
    suite = SuiteRun2(tuple(members), value["suite_hash"], value["contract"])
    if canonical_suite_run2_bytes(suite) != data:
        raise Engine2EvidenceError("suite", "must be canonical JSON bytes")
    return suite


def exact_replay_result2_internal(
    result: Engine2Result | bytes | str, schedule: ScheduleArtifact | bytes | str, scenario: Any,
    *, inputs: Mapping[str, Any] | None = None, plugins: Any = None,
) -> Any:
    """Verify all Result/2 coordinates and observations through exact schedule replay."""
    from .schedule import read_schedule
    evidence = result if isinstance(result, Engine2Result) else read_result2(result)
    recorded = schedule if isinstance(schedule, ScheduleArtifact) else read_schedule(schedule)
    manifest = evidence.manifest
    checks = (
        ("scenario_hash", manifest.scenario_hash, recorded.scenario_hash),
        ("input_resource_hashes", dict(manifest.input_resource_hashes), dict(recorded.input_resource_hashes)),
        ("root_seed", manifest.root_seed, recorded.execution.root_seed),
        ("schedule_seed", manifest.schedule_seed, recorded.schedule_seed),
        ("scheduler_contract", manifest.scheduler_contract, recorded.scheduler_contract),
        ("run_index", manifest.run_index, recorded.run_index),
        ("schedule_hash", evidence.schedule_reference.schedule_hash, recorded.schedule_hash),
        ("dsl_version", manifest.dsl_version, recorded.execution.dsl_version),
        ("engine_version", manifest.engine_version, recorded.execution.engine_version),
        ("reference_clock_start", manifest.reference_clock_start, recorded.execution.reference_clock_start),
        ("generator_versions", dict(manifest.generator_versions), dict(recorded.execution.generator_versions)),
    )
    for field_name, expected, received in checks:
        if expected != received:
            raise Engine2ReplayMismatch(field_name, "evidence coordinates do not match")
    replay = exact_replay_internal(recorded, scenario, inputs=inputs, plugins=plugins)
    observed = construct_result2(scenario, replay)
    comparisons = (
        ("final_state", evidence.final_state, observed.final_state),
        ("final_logical_clock", evidence.final_logical_clock, observed.final_logical_clock),
        ("history", evidence.history, observed.history), ("artifacts", evidence.artifacts, observed.artifacts),
        ("actors", evidence.actors, observed.actors), ("classification", evidence.classification, observed.classification),
        ("failure", evidence.failure, observed.failure),
    )
    for field_name, expected, received in comparisons:
        if expected != received:
            raise Engine2ReplayMismatch(field_name, "replayed observation does not match result")
    return replay


def validate_engine2(yaml_text: str) -> Any:
    """Parse and compile one DSL 2 definition, rejecting every other DSL version."""
    from .dsl import CompiledScenarioV2, compile_document, parse_yaml
    scenario = compile_document(parse_yaml(yaml_text))
    if not isinstance(scenario, CompiledScenarioV2):
        raise Engine2EvidenceError("dsl_version", "Engine 2 requires a DSL 2 definition")
    return scenario


def execute_engine2(
    scenario: Any, root_seed: str | int, schedule_seed: int, *, run_index: int = 0,
    inputs: Mapping[str, Any] | None = None, plugins: Any = None,
) -> tuple[Engine2Result, ScheduleArtifact]:
    """Execute validated DSL 2 actors and return immutable Result/2 and Schedule/1."""
    from .dsl import CompiledScenarioV2
    from .dsl.actor_runtime import execute_actors_internal
    if not isinstance(scenario, CompiledScenarioV2):
        raise TypeError("scenario must be a validated CompiledScenarioV2")
    outcome = execute_actors_internal(
        scenario, root_seed, schedule_seed, run_index=run_index, inputs=inputs, plugins=plugins,
    )
    result = construct_result2(scenario, outcome)
    return result, outcome.schedule


def replay_engine2(
    result: Engine2Result | bytes | str, schedule: ScheduleArtifact | bytes | str,
    scenario: Any, *, inputs: Mapping[str, Any] | None = None, plugins: Any = None,
) -> Engine2Result:
    """Exactly replay supplied Result/2 and Schedule/1 evidence and return Result/2."""
    evidence = result if isinstance(result, Engine2Result) else read_result2(result)
    exact_replay_result2_internal(evidence, schedule, scenario, inputs=inputs, plugins=plugins)
    return evidence


__all__ = (
    "Engine2EvidenceBoundError", "Engine2EvidenceError", "Engine2Manifest",
    "Engine2ReplayMismatch", "Engine2Result", "ScheduleReference",
    "canonical_manifest2_bytes", "canonical_manifest2_identity_bytes",
    "canonical_result2_bytes", "canonical_result2_identity_bytes", "execute_engine2",
    "read_manifest2", "read_result2", "replay_engine2", "validate_engine2",
)
