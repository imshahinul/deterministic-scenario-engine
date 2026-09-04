"""Immutable explicit models for deterministic batch execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import re
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from scenario_engine.canonical import canonical_scenario_hash
from scenario_engine.composition import ComposedSuite
from scenario_engine.dsl import CompiledScenario
from scenario_engine.matrix import MatrixPlan, select_matrix_case
from scenario_engine.plugins import PluginRegistry
from scenario_engine.result import ScenarioResult
from scenario_engine.suite import (
    BATCH_CONTRACT_VERSION, BatchItemResult, BatchResultEnvelope, MatrixCase,
)
from scenario_engine.values import normalize

from .canonical import BATCH_PLAN_IDENTITY_VERSION, canonical_hash
from .errors import (
    BatchPlanError, BatchSizeBoundError, DuplicateRunIdentityError,
    UnsupportedBatchItemError,
)


MAX_BATCH_ITEMS = 10_000
MAX_WORKERS = 64
MAX_IN_FLIGHT = 64
DEFAULT_RETAINED_RESULT_BYTES = 256 * 1024 * 1024
_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@/-]{0,255}\Z")


class ExecutionMode(str, Enum):
    DIRECT = "direct"
    COMPOSED = "composed"
    MATRIX_CASE = "matrix_case"


def _freeze(value: Any) -> Any:
    normalize(value)
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise BatchPlanError("batch inputs require string mapping keys")
        return MappingProxyType({key: _freeze(value[key]) for key in sorted(value)})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _plugin_versions(registry: PluginRegistry | None) -> Mapping[str, str]:
    if registry is None:
        return MappingProxyType({})
    if not isinstance(registry, PluginRegistry):
        raise BatchPlanError("plugins must be an explicit PluginRegistry")
    return MappingProxyType({item.name: item.version for item in registry})


@dataclass(frozen=True, slots=True)
class RunRequest:
    """One explicit independently addressed accepted engine operation."""

    run_id: str
    target: CompiledScenario | ComposedSuite | MatrixPlan = field(compare=False, repr=False)
    root_seed: str | int
    run_index: int = 0
    locale: str = "C"
    inputs: Mapping[str, Any] = field(default_factory=dict)
    plugins: PluginRegistry | None = field(default=None, compare=False, repr=False)
    execution_mode: ExecutionMode = ExecutionMode.DIRECT
    matrix_case: MatrixCase | None = None
    plan_position: int = field(default=-1, compare=False)
    child_identity: str = field(init=False)
    request_identity: str = field(init=False)
    plugin_versions: Mapping[str, str] = field(init=False, compare=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, str) or _RUN_ID.fullmatch(self.run_id) is None:
            raise BatchPlanError("run_id must be a nonempty portable ASCII label")
        if isinstance(self.root_seed, bool) or not isinstance(self.root_seed, (str, int)):
            raise BatchPlanError("root_seed must be a string or integer")
        if isinstance(self.run_index, bool) or not isinstance(self.run_index, int) or self.run_index < 0:
            raise BatchPlanError("run_index must be a nonnegative integer")
        if not isinstance(self.locale, str) or not self.locale:
            raise BatchPlanError("locale must be an explicit nonempty string")
        if not isinstance(self.execution_mode, ExecutionMode):
            raise UnsupportedBatchItemError("execution_mode is unsupported")
        if self.plan_position != -1 and (
            isinstance(self.plan_position, bool)
            or not isinstance(self.plan_position, int)
            or self.plan_position < 0
        ):
            raise BatchPlanError("plan_position must be assigned by BatchPlan")
        try:
            inputs = _freeze(self.inputs)
        except (TypeError, ValueError):
            raise BatchPlanError("inputs contain an invalid semantic value") from None
        if not isinstance(inputs, Mapping):
            raise BatchPlanError("inputs must be a string-keyed mapping")
        versions = _plugin_versions(self.plugins)
        child_identity, extra = self._validate_target()
        payload = {
            "child_identity": child_identity,
            "execution_mode": self.execution_mode.value,
            "inputs": inputs,
            "locale": self.locale,
            "matrix": extra,
            "plugin_versions": versions,
            "root_seed": self.root_seed,
            "run_id": self.run_id,
            "run_index": self.run_index,
            "version": BATCH_PLAN_IDENTITY_VERSION,
        }
        object.__setattr__(self, "inputs", inputs)
        object.__setattr__(self, "plugin_versions", versions)
        object.__setattr__(self, "child_identity", child_identity)
        object.__setattr__(self, "request_identity", canonical_hash(payload))

    def _validate_target(self) -> tuple[str, Mapping[str, Any] | None]:
        if self.execution_mode is ExecutionMode.DIRECT:
            if not isinstance(self.target, CompiledScenario) or self.matrix_case is not None:
                raise UnsupportedBatchItemError("direct requests require a CompiledScenario")
            return "scenario:" + canonical_scenario_hash(self.target), None
        if self.execution_mode is ExecutionMode.COMPOSED:
            if not isinstance(self.target, ComposedSuite) or self.matrix_case is not None:
                raise UnsupportedBatchItemError("composed requests require a ComposedSuite")
            return "suite:" + self.target.composed_hash, None
        if not isinstance(self.target, MatrixPlan) or not isinstance(self.matrix_case, MatrixCase):
            raise UnsupportedBatchItemError("matrix_case requests require a MatrixPlan and MatrixCase")
        expected = select_matrix_case(self.target, self.matrix_case.case_id)
        if expected != self.matrix_case:
            raise UnsupportedBatchItemError("matrix case does not match its plan")
        if (
            self.root_seed != self.target.root_seed
            or self.run_index != self.matrix_case.case_index
            or self.locale != self.target.locale
        ):
            raise BatchPlanError("matrix request execution coordinates do not match its plan case")
        return "matrix-case:" + self.matrix_case.case_id, {
            "case_id": self.matrix_case.case_id,
            "original_index": self.matrix_case.case_index,
            "matrix_plan_id": self.target.plan_id,
        }


@dataclass(frozen=True, slots=True)
class BatchPlan:
    """A finite immutable ordered sequence of explicit run requests."""

    items: tuple[RunRequest, ...] = ()
    fail_fast: bool = False
    retained_result_bytes: int = DEFAULT_RETAINED_RESULT_BYTES
    plan_hash: str = field(init=False)
    plan_identity: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.items, Sequence) or isinstance(
            self.items, (str, bytes, Mapping, set, frozenset)
        ):
            raise BatchPlanError("items must be an explicit ordered sequence")
        if len(self.items) > MAX_BATCH_ITEMS:
            raise BatchSizeBoundError(f"batch exceeds {MAX_BATCH_ITEMS} requests")
        source = tuple(self.items)
        if not all(isinstance(item, RunRequest) for item in source):
            raise UnsupportedBatchItemError("items must contain RunRequest values")
        if not isinstance(self.fail_fast, bool):
            raise BatchPlanError("fail_fast must be boolean")
        if (
            isinstance(self.retained_result_bytes, bool)
            or not isinstance(self.retained_result_bytes, int)
            or self.retained_result_bytes <= 0
        ):
            raise BatchPlanError("retained_result_bytes must be a positive integer")
        run_ids = [item.run_id for item in source]
        if len(run_ids) != len(set(run_ids)):
            raise DuplicateRunIdentityError("batch contains a duplicate run_id")
        positioned = tuple(_at_position(item, position) for position, item in enumerate(source))
        plan_hash = canonical_hash({
            "contract_version": BATCH_CONTRACT_VERSION,
            "fail_fast": self.fail_fast,
            "request_identities": [item.request_identity for item in positioned],
            "retained_result_bytes": self.retained_result_bytes,
        })
        object.__setattr__(self, "items", positioned)
        object.__setattr__(self, "plan_hash", plan_hash)
        object.__setattr__(self, "plan_identity", "batch:" + plan_hash)


def _at_position(item: RunRequest, position: int) -> RunRequest:
    return RunRequest(
        run_id=item.run_id, target=item.target, root_seed=item.root_seed,
        run_index=item.run_index, locale=item.locale, inputs=item.inputs,
        plugins=item.plugins, execution_mode=item.execution_mode,
        matrix_case=item.matrix_case, plan_position=position,
    )


@dataclass(frozen=True, slots=True)
class BatchExecutionItem:
    """One ordered execution observation and its Phase 2.1 item record."""

    request: RunRequest
    record: BatchItemResult
    result: ScenarioResult | None = field(default=None, compare=False, repr=False)
    retained_bytes: int = field(default=0, compare=False, repr=False)


@dataclass(frozen=True, slots=True)
class BatchExecution:
    """Materialized ordered child observations and canonical result envelope."""

    plan: BatchPlan
    items: tuple[BatchExecutionItem, ...]
    envelope: BatchResultEnvelope

    @property
    def results(self) -> tuple[ScenarioResult | None, ...]:
        return tuple(item.result for item in self.items)
