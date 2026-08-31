"""Same-version reproducibility contract for Phase 0.2A."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Mapping

from .ids import ID_VERSION
from .rng import RNG_VERSION
from .values import normalize


ENGINE_VERSION = "0.2.0.dev0"
GENERATOR_VERSIONS = MappingProxyType({"int": RNG_VERSION, "logical_id": ID_VERSION})


class ReplayCompatibilityError(ValueError):
    """A manifest cannot be replayed by this exact engine contract."""


def _frozen_strings(value: Mapping[str, str], field_name: str) -> Mapping[str, str]:
    if not all(isinstance(key, str) and isinstance(item, str) for key, item in value.items()):
        raise TypeError(f"{field_name} must map strings to strings")
    return MappingProxyType({key: value[key] for key in sorted(value)})


@dataclass(frozen=True, slots=True)
class ReproducibilityManifest:
    root_seed: str | int
    scenario_canonical_hash: str
    engine_version: str
    dsl_version: int
    input_resource_hashes: Mapping[str, str] = field(default_factory=dict)
    domain_pack_versions: Mapping[str, str] = field(default_factory=dict)
    generator_versions: Mapping[str, str] = field(default_factory=lambda: GENERATOR_VERSIONS)
    rng_algorithm_version: str = RNG_VERSION
    id_algorithm_version: str = ID_VERSION
    locale: str = "C"
    reference_clock_start: datetime | None = None
    run_index: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.root_seed, (str, int)):
            raise TypeError("root_seed must be a string or integer")
        if isinstance(self.run_index, bool) or not isinstance(self.run_index, int) or self.run_index < 0:
            raise ValueError("run_index must be a nonnegative integer")
        if not isinstance(self.locale, str) or not self.locale:
            raise ValueError("locale must be a non-empty explicit string")
        if self.reference_clock_start is None:
            raise ValueError("reference_clock_start is required")
        normalize(self.reference_clock_start)
        object.__setattr__(self, "reference_clock_start",
                           self.reference_clock_start.astimezone(timezone.utc))
        object.__setattr__(self, "input_resource_hashes", _frozen_strings(
            self.input_resource_hashes, "input_resource_hashes"))
        object.__setattr__(self, "domain_pack_versions", _frozen_strings(
            self.domain_pack_versions, "domain_pack_versions"))
        object.__setattr__(self, "generator_versions", _frozen_strings(
            self.generator_versions, "generator_versions"))

    def normalized(self) -> Mapping[str, Any]:
        return normalize({
            "domain_pack_versions": self.domain_pack_versions,
            "dsl_version": self.dsl_version,
            "engine_version": self.engine_version,
            "generator_versions": self.generator_versions,
            "id_algorithm_version": self.id_algorithm_version,
            "input_resource_hashes": self.input_resource_hashes,
            "locale": self.locale,
            "reference_clock_start": self.reference_clock_start,
            "rng_algorithm_version": self.rng_algorithm_version,
            "root_seed": self.root_seed,
            "run_index": self.run_index,
            "scenario_canonical_hash": self.scenario_canonical_hash,
        })

    def to_jsonable(self) -> Mapping[str, Any]:
        return self.normalized()
