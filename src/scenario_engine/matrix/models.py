"""Immutable models for ordered deterministic scenario matrices."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from scenario_engine.composition import ComposedSuite
from scenario_engine.dsl import CompiledScenario
from scenario_engine.result import ScenarioResult
from scenario_engine.suite import MatrixCase, MatrixManifest, MatrixResultEnvelope
from scenario_engine.values import normalize

from .canonical import matrix_plan_hash
from .errors import MatrixDeclarationError, MatrixDimensionError


MAX_DIMENSIONS = 16
MAX_VALUES_PER_DIMENSION = 1_000
MAX_RAW_CARDINALITY = 100_000
MAX_RETAINED_CASES = 10_000
_NAME = re.compile(r"[a-z][a-z0-9_]*\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")


def _freeze(value: Any) -> Any:
    normalize(value)
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise MatrixDeclarationError("matrix semantic mappings require string keys")
        return MappingProxyType({key: _freeze(value[key]) for key in sorted(value)})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class MatrixDimension:
    """One explicitly ordered parameter dimension."""

    name: str
    values: tuple[Any, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or _NAME.fullmatch(self.name) is None:
            raise MatrixDimensionError("dimension name must match [a-z][a-z0-9_]*")
        if isinstance(self.values, (str, bytes, Mapping, set, frozenset)):
            raise MatrixDimensionError("dimension values must be an explicit ordered sequence")
        try:
            values = tuple(self.values)
        except TypeError:
            raise MatrixDimensionError("dimension values must be an explicit ordered sequence") from None
        if not values:
            raise MatrixDimensionError("dimension values must be nonempty")
        if len(values) > MAX_VALUES_PER_DIMENSION:
            raise MatrixDimensionError(f"dimension exceeds {MAX_VALUES_PER_DIMENSION} values")
        try:
            object.__setattr__(self, "values", tuple(_freeze(item) for item in values))
        except (TypeError, ValueError):
            raise MatrixDimensionError("dimension contains an invalid semantic value") from None


@dataclass(frozen=True, slots=True)
class MatrixPlan:
    """A path-free immutable matrix definition and explicit execution context."""

    suite_identity: str
    suite_hash: str
    dimensions: tuple[MatrixDimension, ...] = ()
    filters: tuple[Mapping[str, Any], ...] = ()
    root_seed: str | int = 0
    locale: str = "C"
    target: ComposedSuite | CompiledScenario | None = field(default=None, compare=False, repr=False)
    plan_id: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.suite_identity, str) or not self.suite_identity:
            raise MatrixDeclarationError("suite_identity must be nonempty")
        if not isinstance(self.suite_hash, str) or _HASH.fullmatch(self.suite_hash) is None:
            raise MatrixDeclarationError("suite_hash must be lowercase SHA-256")
        if isinstance(self.root_seed, bool) or not isinstance(self.root_seed, (str, int)):
            raise MatrixDeclarationError("root_seed must be a string or integer")
        if not isinstance(self.locale, str) or not self.locale:
            raise MatrixDeclarationError("locale must be an explicit nonempty string")
        dimensions = tuple(self.dimensions)
        if len(dimensions) > MAX_DIMENSIONS:
            raise MatrixDimensionError(f"matrix exceeds {MAX_DIMENSIONS} dimensions")
        if not all(isinstance(item, MatrixDimension) for item in dimensions):
            raise MatrixDimensionError("dimensions must contain MatrixDimension values")
        names = [item.name for item in dimensions]
        if len(names) != len(set(names)):
            raise MatrixDimensionError("matrix contains a duplicate dimension name")
        filters = tuple(_freeze(item) for item in self.filters)
        if not all(isinstance(item, Mapping) for item in filters):
            raise MatrixDeclarationError("filters must be expression mappings")
        if self.target is not None and not isinstance(self.target, (ComposedSuite, CompiledScenario)):
            raise MatrixDeclarationError("target must be a ComposedSuite or CompiledScenario")
        object.__setattr__(self, "dimensions", dimensions)
        object.__setattr__(self, "filters", filters)
        object.__setattr__(self, "plan_id", matrix_plan_hash(self.suite_hash, dimensions, filters))


@dataclass(frozen=True, slots=True)
class MatrixExecution:
    """Ordered successful results plus the Phase 2.1 matrix envelopes."""

    plan: MatrixPlan
    cases: tuple[MatrixCase, ...]
    results: tuple[ScenarioResult, ...]
    manifest: MatrixManifest
    envelope: MatrixResultEnvelope

    def __post_init__(self) -> None:
        if len(self.cases) != len(self.results):
            raise MatrixDeclarationError("matrix execution case/result lengths differ")
        if tuple(item.case_index for item in self.cases) != tuple(
            item.manifest.run_index for item in self.results
        ):
            raise MatrixDeclarationError("matrix result addressing mismatch")
