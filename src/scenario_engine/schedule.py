"""Internal canonical ``scenario.schedule/1`` evidence and exact replay."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .canonical import canonical_scenario_hash
from .ids import ID_VERSION
from .manifest import GENERATOR_VERSIONS
from .plugins import EMPTY_PLUGIN_REGISTRY, PluginRegistry
from .resources import resolve_resources
from .rng import RNG_VERSION
from .scheduler import (
    MAX_ACTORS, MAX_SCHEDULE_SEED, MAX_SCHEDULER_SELECTIONS, SCHEDULER_CONTRACT,
    SchedulerInput,
)
from .values import canonical_bytes


SCHEDULE_CONTRACT = "scenario.schedule/1"
ENGINE2_EXECUTION_VERSION = "2.0.0"
MAX_CANONICAL_SCHEDULE_BYTES = 8_388_608
MAX_REPLAY_SCHEDULER_SELECTIONS_VERIFIED = 65_536
MAX_SCHEDULE_NESTING_DEPTH = 32
_HASH = re.compile(r"[0-9a-f]{64}\Z")


class ScheduleError(ValueError):
    """Base fail-closed schedule diagnostic with no supplied-value reflection."""

    code = "SCHEDULE_INVALID"

    def __init__(self, field: str, message: str, *, code: str | None = None) -> None:
        self.field = field
        if code is not None:
            self.code = code
        super().__init__(f"{field}: {message}")


class ScheduleBoundError(ScheduleError):
    code = "SCHEDULE_BOUND_EXCEEDED"


class ScheduleReplayMismatch(ScheduleError):
    code = "SCHEDULE_REPLAY_MISMATCH"


def _integer(value: object, field: str, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ScheduleError(field, "must be a nonnegative integer excluding bool")
    if maximum is not None and value > maximum:
        raise ScheduleBoundError(field, f"exceeds inclusive maximum {maximum}")
    return value


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ScheduleError(field, "must be a nonempty string")
    return value


def _hash(value: object, field: str) -> str:
    if not isinstance(value, str) or _HASH.fullmatch(value) is None:
        raise ScheduleError(field, "must be 64 lowercase hexadecimal characters")
    return value


def _strings(value: object, field: str) -> Mapping[str, str]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) and isinstance(item, str) for key, item in value.items()
    ):
        raise ScheduleError(field, "must map strings to strings")
    return MappingProxyType({key: value[key] for key in sorted(value)})


def _clock(value: object, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ScheduleError(field, "must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _actors(value: object, field: str, *, nonempty: bool = True) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ScheduleError(field, "must be a sequence of actor addresses")
    if nonempty and not value:
        raise ScheduleError(field, "must not be empty")
    if len(value) > MAX_ACTORS:
        raise ScheduleBoundError(field, f"exceeds inclusive maximum {MAX_ACTORS}")
    # SchedulerInput owns the frozen semantic-address validator and canonical order.
    probe = SchedulerInput(
        "0" * 64, {}, 0, 0, 0, 0, datetime(1970, 1, 1, tzinfo=timezone.utc),
        value, (value[0],) if value else (),
    )
    checked = tuple(probe.declared_actors)
    if tuple(value) != checked:
        raise ScheduleError(field, "must be in canonical UTF-8 byte order")
    return checked


@dataclass(frozen=True, slots=True)
class ScheduleExecution:
    root_seed: str | int
    reference_clock_start: datetime
    generator_versions: Mapping[str, str]
    rng_algorithm_version: str = RNG_VERSION
    id_algorithm_version: str = ID_VERSION
    locale: str = "C"
    engine_version: str = ENGINE2_EXECUTION_VERSION
    dsl_version: int = 2

    def __post_init__(self) -> None:
        if isinstance(self.root_seed, bool) or not isinstance(self.root_seed, (str, int)):
            raise ScheduleError("execution.root_seed", "must be a string or integer excluding bool")
        object.__setattr__(self, "reference_clock_start", _clock(
            self.reference_clock_start, "execution.reference_clock_start",
        ))
        object.__setattr__(self, "generator_versions", _strings(
            self.generator_versions, "execution.generator_versions",
        ))
        if self.dsl_version != 2 or isinstance(self.dsl_version, bool):
            raise ScheduleError("execution.dsl_version", "unsupported version")
        if self.engine_version != ENGINE2_EXECUTION_VERSION:
            raise ScheduleError("execution.engine_version", "unsupported version")
        if self.locale != "C":
            raise ScheduleError("execution.locale", "unsupported locale")
        if self.rng_algorithm_version != RNG_VERSION:
            raise ScheduleError("execution.rng_algorithm_version", "unsupported version")
        if self.id_algorithm_version != ID_VERSION:
            raise ScheduleError("execution.id_algorithm_version", "unsupported version")

    def payload(self) -> Mapping[str, Any]:
        return {
            "dsl_version": self.dsl_version, "engine_version": self.engine_version,
            "generator_versions": self.generator_versions,
            "id_algorithm_version": self.id_algorithm_version, "locale": self.locale,
            "reference_clock_start": self.reference_clock_start,
            "rng_algorithm_version": self.rng_algorithm_version, "root_seed": self.root_seed,
        }


@dataclass(frozen=True, slots=True)
class ScheduleRecord:
    selection_ordinal: int
    ready_actors: tuple[str, ...]
    selected_actor: str
    committed_history_length: int
    logical_clock: datetime
    scheduler_digest: str
    outcome: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "selection_ordinal", _integer(
            self.selection_ordinal, "records.selection_ordinal", MAX_SCHEDULER_SELECTIONS - 1,
        ))
        ready = _actors(self.ready_actors, "records.ready_actors")
        object.__setattr__(self, "ready_actors", ready)
        if self.selected_actor not in ready:
            raise ScheduleError("records.selected_actor", "must be a ready actor")
        object.__setattr__(self, "committed_history_length", _integer(
            self.committed_history_length, "records.committed_history_length",
        ))
        object.__setattr__(self, "logical_clock", _clock(self.logical_clock, "records.logical_clock"))
        object.__setattr__(self, "scheduler_digest", _hash(
            self.scheduler_digest, "records.scheduler_digest",
        ))
        if self.outcome not in ("COMMITTED", "FAILED"):
            raise ScheduleError("records.outcome", "must be COMMITTED or FAILED")

    def payload(self) -> Mapping[str, Any]:
        return {
            "committed_history_length": self.committed_history_length,
            "logical_clock": self.logical_clock, "outcome": self.outcome,
            "ready_actors": self.ready_actors, "scheduler_digest": self.scheduler_digest,
            "selected_actor": self.selected_actor, "selection_ordinal": self.selection_ordinal,
        }


@dataclass(frozen=True, slots=True)
class ScheduleFailure:
    actor: str
    code: str
    selection_ordinal: int

    def __post_init__(self) -> None:
        _actors((self.actor,), "terminal.failure.actor")
        _string(self.code, "terminal.failure.code")
        _integer(self.selection_ordinal, "terminal.failure.selection_ordinal", MAX_SCHEDULER_SELECTIONS - 1)

    def payload(self) -> Mapping[str, Any]:
        return {"actor": self.actor, "code": self.code, "selection_ordinal": self.selection_ordinal}


@dataclass(frozen=True, slots=True)
class ScheduleArtifact:
    scenario_hash: str
    input_resource_hashes: Mapping[str, str]
    run_index: int
    schedule_seed: int
    actors: tuple[str, ...]
    execution: ScheduleExecution
    records: tuple[ScheduleRecord, ...]
    classification: str
    failure: ScheduleFailure | None
    schedule_hash: str = ""
    contract: str = SCHEDULE_CONTRACT
    scheduler_contract: str = SCHEDULER_CONTRACT

    def __post_init__(self) -> None:
        if self.contract != SCHEDULE_CONTRACT:
            raise ScheduleError("contract", "unsupported contract")
        if self.scheduler_contract != SCHEDULER_CONTRACT:
            raise ScheduleError("scheduler_contract", "unsupported contract")
        object.__setattr__(self, "scenario_hash", _hash(self.scenario_hash, "scenario_hash"))
        object.__setattr__(self, "input_resource_hashes", _strings(
            self.input_resource_hashes, "input_resource_hashes",
        ))
        object.__setattr__(self, "run_index", _integer(self.run_index, "run_index"))
        object.__setattr__(self, "schedule_seed", _integer(
            self.schedule_seed, "schedule_seed", MAX_SCHEDULE_SEED,
        ))
        object.__setattr__(self, "actors", _actors(self.actors, "actors"))
        if not isinstance(self.execution, ScheduleExecution):
            raise ScheduleError("execution", "must be ScheduleExecution")
        records = tuple(self.records)
        if len(records) > MAX_SCHEDULER_SELECTIONS:
            raise ScheduleBoundError("records", "exceeds MAX_SCHEDULER_SELECTIONS")
        for index, record in enumerate(records):
            if not isinstance(record, ScheduleRecord) or record.selection_ordinal != index:
                raise ScheduleError("records", "ordinals must equal list positions")
            if any(actor not in self.actors for actor in record.ready_actors):
                raise ScheduleError("records.ready_actors", "contains an undeclared actor")
            if record.outcome == "FAILED" and index != len(records) - 1:
                raise ScheduleError("records.outcome", "only the final record may be FAILED")
        object.__setattr__(self, "records", records)
        if self.classification == "SUCCESS":
            if self.failure is not None or any(record.outcome != "COMMITTED" for record in records):
                raise ScheduleError("terminal", "SUCCESS requires committed records and null failure")
        elif self.classification == "FAILED":
            if not records or records[-1].outcome != "FAILED" or self.failure is None:
                raise ScheduleError("terminal", "FAILED requires a final failed record and failure")
            if (self.failure.actor != records[-1].selected_actor or
                    self.failure.selection_ordinal != records[-1].selection_ordinal):
                raise ScheduleError("terminal.failure", "must identify the final failed record")
        else:
            raise ScheduleError("terminal.classification", "must be SUCCESS or FAILED")
        identity = canonical_schedule_identity_bytes(self)
        digest = hashlib.sha256(identity).hexdigest()
        if self.schedule_hash and _hash(self.schedule_hash, "schedule_hash") != digest:
            raise ScheduleError("schedule_hash", "does not match the canonical identity payload")
        object.__setattr__(self, "schedule_hash", digest)
        if len(canonical_schedule_bytes(self)) > MAX_CANONICAL_SCHEDULE_BYTES:
            raise ScheduleBoundError("schedule", "exceeds MAX_CANONICAL_SCHEDULE_BYTES")

    def identity_payload(self) -> Mapping[str, Any]:
        return {
            "actors": self.actors, "contract": self.contract,
            "execution": self.execution.payload(),
            "input_resource_hashes": self.input_resource_hashes,
            "records": tuple(record.payload() for record in self.records),
            "run_index": self.run_index, "scenario_hash": self.scenario_hash,
            "schedule_seed": self.schedule_seed, "scheduler_contract": self.scheduler_contract,
            "terminal": {"classification": self.classification,
                         "failure": None if self.failure is None else self.failure.payload()},
        }

    def payload(self) -> Mapping[str, Any]:
        return {**self.identity_payload(), "schedule_hash": self.schedule_hash}


def canonical_schedule_identity_bytes(schedule: ScheduleArtifact) -> bytes:
    encoded = canonical_bytes(schedule.identity_payload())
    if len(encoded) > MAX_CANONICAL_SCHEDULE_BYTES:
        raise ScheduleBoundError("schedule", "exceeds MAX_CANONICAL_SCHEDULE_BYTES")
    return encoded


def canonical_schedule_bytes(schedule: ScheduleArtifact) -> bytes:
    encoded = canonical_bytes(schedule.payload())
    if len(encoded) > MAX_CANONICAL_SCHEDULE_BYTES:
        raise ScheduleBoundError("schedule", "exceeds MAX_CANONICAL_SCHEDULE_BYTES")
    return encoded


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ScheduleError("json", "contains a duplicate key")
        result[key] = value
    return result


def _depth(value: Any, level: int = 0) -> None:
    if level > MAX_SCHEDULE_NESTING_DEPTH:
        raise ScheduleBoundError("json", "exceeds maximum nesting depth")
    if isinstance(value, Mapping):
        for item in value.values(): _depth(item, level + 1)
    elif isinstance(value, list):
        for item in value: _depth(item, level + 1)


def _exact(value: object, fields: set[str], name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ScheduleError(name, "has missing or unknown fields")
    return value


def _datetime_wire(value: object, field: str) -> datetime:
    item = _exact(value, {"$type", "value"}, field)
    if item["$type"] != "datetime" or not isinstance(item["value"], str):
        raise ScheduleError(field, "must use canonical datetime encoding")
    try:
        parsed = datetime.fromisoformat(item["value"])
    except ValueError:
        raise ScheduleError(field, "must use canonical datetime encoding") from None
    parsed = _clock(parsed, field)
    if canonical_bytes(parsed) != canonical_bytes(value):
        raise ScheduleError(field, "must use canonical datetime encoding")
    return parsed


def read_schedule(source: bytes | str) -> ScheduleArtifact:
    if not isinstance(source, (bytes, str)):
        raise TypeError("source must be bytes or str")
    raw_bytes = source if isinstance(source, bytes) else source.encode("utf-8")
    if len(raw_bytes) > MAX_CANONICAL_SCHEDULE_BYTES:
        raise ScheduleBoundError("schedule", "exceeds MAX_CANONICAL_SCHEDULE_BYTES")
    try:
        text = raw_bytes.decode("utf-8")
        raw = json.loads(text, object_pairs_hook=_unique_object,
                         parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except ScheduleError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError):
        raise ScheduleError("json", "must be strict UTF-8 JSON") from None
    _depth(raw)
    top = _exact(raw, {"actors", "contract", "execution", "input_resource_hashes", "records",
                       "run_index", "scenario_hash", "schedule_hash", "schedule_seed",
                       "scheduler_contract", "terminal"}, "schedule")
    execution = _exact(top["execution"], {"dsl_version", "engine_version", "generator_versions",
        "id_algorithm_version", "locale", "reference_clock_start", "rng_algorithm_version",
        "root_seed"}, "execution")
    if not isinstance(top["records"], list):
        raise ScheduleError("records", "must be a list")
    if len(top["records"]) > min(MAX_SCHEDULER_SELECTIONS, MAX_REPLAY_SCHEDULER_SELECTIONS_VERIFIED):
        raise ScheduleBoundError("records", "exceeds replay selection ceiling")
    records = []
    record_fields = {"committed_history_length", "logical_clock", "outcome", "ready_actors",
                     "scheduler_digest", "selected_actor", "selection_ordinal"}
    for index, value in enumerate(top["records"]):
        item = _exact(value, record_fields, f"records[{index}]")
        records.append(ScheduleRecord(
            item["selection_ordinal"], tuple(item["ready_actors"]) if isinstance(item["ready_actors"], list) else item["ready_actors"],
            item["selected_actor"], item["committed_history_length"],
            _datetime_wire(item["logical_clock"], f"records[{index}].logical_clock"),
            item["scheduler_digest"], item["outcome"],
        ))
    terminal = _exact(top["terminal"], {"classification", "failure"}, "terminal")
    failure = None
    if terminal["failure"] is not None:
        item = _exact(terminal["failure"], {"actor", "code", "selection_ordinal"}, "terminal.failure")
        failure = ScheduleFailure(item["actor"], item["code"], item["selection_ordinal"])
    artifact = ScheduleArtifact(
        top["scenario_hash"], top["input_resource_hashes"], top["run_index"], top["schedule_seed"],
        tuple(top["actors"]) if isinstance(top["actors"], list) else top["actors"],
        ScheduleExecution(execution["root_seed"],
            _datetime_wire(execution["reference_clock_start"], "execution.reference_clock_start"),
            execution["generator_versions"], execution["rng_algorithm_version"],
            execution["id_algorithm_version"], execution["locale"],
            execution["engine_version"], execution["dsl_version"]),
        tuple(records), terminal["classification"], failure, top["schedule_hash"],
        top["contract"], top["scheduler_contract"],
    )
    if canonical_schedule_bytes(artifact) != raw_bytes:
        raise ScheduleError("schedule", "must be canonical JSON bytes")
    return artifact


def exact_replay_internal(
    schedule: ScheduleArtifact | bytes | str, scenario: Any, *, inputs: Mapping[str, Any] | None = None,
    plugins: PluginRegistry | None = None,
) -> Any:
    """Independently replay and verify every scheduler decision and final outcome."""
    source = schedule if isinstance(schedule, ScheduleArtifact) else read_schedule(schedule)
    if len(source.records) > MAX_REPLAY_SCHEDULER_SELECTIONS_VERIFIED:
        raise ScheduleBoundError("records", "exceeds MAX_REPLAY_SCHEDULER_SELECTIONS_VERIFIED")
    if canonical_scenario_hash(scenario) != source.scenario_hash:
        raise ScheduleReplayMismatch("scenario_hash", "does not match replay scenario")
    resources = scenario.resources if scenario.resources is not None else resolve_resources(scenario.document.resources, inputs)
    if dict(resources.hashes()) != dict(source.input_resource_hashes):
        raise ScheduleReplayMismatch("input_resource_hashes", "does not match replay resources")
    registry = EMPTY_PLUGIN_REGISTRY if plugins is None else plugins
    from .dsl.actor_runtime import execute_actors_internal
    try:
        outcome = execute_actors_internal(
            scenario, source.execution.root_seed, source.schedule_seed,
            run_index=source.run_index, inputs=inputs, plugins=registry, _expected_schedule=source,
        )
    except ScheduleReplayMismatch:
        raise
    except Exception as error:
        outcome = getattr(error, "internal_outcome", None)
        if outcome is None or outcome.schedule != source:
            raise ScheduleReplayMismatch("terminal", "failed outcome does not match schedule") from None
        return outcome
    if outcome.schedule != source:
        raise ScheduleReplayMismatch("terminal", "completed outcome does not match schedule")
    return outcome
