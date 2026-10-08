"""Pure deterministic ``scenario.scheduler/1`` selection kernel."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import re
from types import MappingProxyType
from typing import Mapping, Sequence
from urllib.parse import unquote

from .diagnostics import semantic_address
from .errors import ScenarioEngineError
from .values import canonical_bytes, normalize


SCHEDULER_CONTRACT = "scenario.scheduler/1"
MAX_SCHEDULE_SEED = (1 << 64) - 1
MAX_SELECTION_ORDINAL = 65_535
MAX_SCHEDULER_SELECTIONS = 65_536
MAX_ACTORS = 32
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_ACTOR_PREFIX = "scenario:/actor/"


class SchedulerValidationError(ScenarioEngineError, ValueError):
    """A scheduler coordinate failed closed validation."""

    code = "SCHEDULER_COORDINATE_INVALID"
    category = "SCHEDULER"

    def __init__(self, field_name: str, message: str, *, limit: str | None = None) -> None:
        self.field_name = field_name
        self.limit = limit
        super().__init__(f"{field_name}: {message}")


def _integer(value: object, name: str, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SchedulerValidationError(name, "must be a nonnegative integer excluding bool")
    if maximum is not None and value > maximum:
        raise SchedulerValidationError(name, f"exceeds inclusive maximum {maximum}", limit=name.upper())
    return value


def _actor_address(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.startswith(_ACTOR_PREFIX):
        raise SchedulerValidationError(name, "must be a canonical actor semantic address")
    token = value[len(_ACTOR_PREFIX):]
    if not token or "/" in token:
        raise SchedulerValidationError(name, "must have exact scenario:/actor/<identifier> shape")
    try:
        identifier = unquote(token, encoding="utf-8", errors="strict")
    except (UnicodeDecodeError, UnicodeError):
        raise SchedulerValidationError(name, "contains invalid UTF-8 escaping") from None
    if semantic_address(("actor", identifier), activate_actor=True) != value:
        raise SchedulerValidationError(name, "is not canonical scenario.semantic-address/1")
    return value


def _actors(values: object, name: str, *, nonempty: bool) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise SchedulerValidationError(name, "must be a sequence of actor addresses")
    if nonempty and not values:
        raise SchedulerValidationError(name, "must not be empty")
    if len(values) > MAX_ACTORS:
        raise SchedulerValidationError(name, f"exceeds inclusive maximum {MAX_ACTORS}", limit="MAX_ACTORS")
    checked: list[str] = []
    seen: set[str] = set()
    for index, value in enumerate(values):
        actor = _actor_address(value, f"{name}[{index}]")
        if actor in seen:
            raise SchedulerValidationError(f"{name}[{index}]", "duplicates an actor address")
        seen.add(actor)
        checked.append(actor)
    return tuple(sorted(checked, key=lambda item: item.encode("utf-8")))


@dataclass(frozen=True, slots=True)
class SchedulerInput:
    """Validated immutable coordinates for one scheduler decision."""

    scenario_hash: str
    input_resource_hashes: Mapping[str, str]
    run_index: int
    schedule_seed: int
    selection_ordinal: int
    committed_history_length: int
    logical_clock: datetime
    declared_actors: Sequence[str]
    ready_actors: Sequence[str]

    def __post_init__(self) -> None:
        if not isinstance(self.scenario_hash, str) or _HASH.fullmatch(self.scenario_hash) is None:
            raise SchedulerValidationError("scenario_hash", "must be 64 lowercase hexadecimal characters")
        if not isinstance(self.input_resource_hashes, Mapping):
            raise SchedulerValidationError("input_resource_hashes", "must be a string-to-string mapping")
        resources: dict[str, str] = {}
        if not all(isinstance(key, str) for key in self.input_resource_hashes):
            raise SchedulerValidationError("input_resource_hashes", "must map strings to strings")
        for key in sorted(self.input_resource_hashes):
            value = self.input_resource_hashes[key]
            if not isinstance(value, str):
                raise SchedulerValidationError("input_resource_hashes", "must map strings to strings")
            resources[key] = value
        object.__setattr__(self, "input_resource_hashes", MappingProxyType(resources))
        object.__setattr__(self, "run_index", _integer(self.run_index, "run_index"))
        object.__setattr__(self, "schedule_seed", _integer(
            self.schedule_seed, "schedule_seed", MAX_SCHEDULE_SEED,
        ))
        object.__setattr__(self, "selection_ordinal", _integer(
            self.selection_ordinal, "selection_ordinal", MAX_SELECTION_ORDINAL,
        ))
        object.__setattr__(self, "committed_history_length", _integer(
            self.committed_history_length, "committed_history_length",
        ))
        if not isinstance(self.logical_clock, datetime):
            raise SchedulerValidationError("logical_clock", "must be a timezone-aware datetime")
        if self.logical_clock.tzinfo is None or self.logical_clock.utcoffset() is None:
            raise SchedulerValidationError("logical_clock", "must be timezone-aware")
        normalize(self.logical_clock)
        declared = _actors(self.declared_actors, "declared_actors", nonempty=True)
        ready = _actors(self.ready_actors, "ready_actors", nonempty=True)
        declared_set = frozenset(declared)
        for index, actor in enumerate(ready):
            if actor not in declared_set:
                raise SchedulerValidationError(f"ready_actors[{index}]", "actor is not declared")
        object.__setattr__(self, "declared_actors", declared)
        object.__setattr__(self, "ready_actors", ready)

    def envelope(self) -> Mapping[str, object]:
        """Return the exact normalized scheduler coordinate envelope."""
        return normalize({
            "contract": SCHEDULER_CONTRACT,
            "coordinates": {
                "scenario_hash": self.scenario_hash,
                "input_resource_hashes": self.input_resource_hashes,
                "run_index": self.run_index,
                "schedule_seed": self.schedule_seed,
                "selection_ordinal": self.selection_ordinal,
                "committed_history_length": self.committed_history_length,
                "logical_clock": self.logical_clock,
                "ready_actors": self.ready_actors,
            },
        })


@dataclass(frozen=True, slots=True)
class SchedulerDecision:
    """Immutable stable result of one pure scheduler selection."""

    contract: str
    canonical_bytes: bytes = field(repr=False)
    digest: str
    selected_index: int
    selected_actor: str
    ready_actors: tuple[str, ...]


def select_actor(coordinates: SchedulerInput) -> SchedulerDecision:
    """Select one ready actor by the frozen ``scenario.scheduler/1`` algorithm."""
    if not isinstance(coordinates, SchedulerInput):
        raise SchedulerValidationError("coordinates", "must be SchedulerInput")
    encoded = canonical_bytes(coordinates.envelope())
    digest = hashlib.sha256(encoded).hexdigest()
    selected_index = int(digest, 16) % len(coordinates.ready_actors)
    return SchedulerDecision(
        contract=SCHEDULER_CONTRACT,
        canonical_bytes=encoded,
        digest=digest,
        selected_index=selected_index,
        selected_actor=coordinates.ready_actors[selected_index],
        ready_actors=tuple(coordinates.ready_actors),
    )
