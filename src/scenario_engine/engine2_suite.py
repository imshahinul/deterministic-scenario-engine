"""Bounded serial Engine 2 suite orchestration and offline verification.

The contracts in this module are additive E2-1 candidates.  Nothing here is
exported from :mod:`scenario_engine` and no existing native evidence contract is
modified.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import hashlib
import json
import re
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .canonical import canonical_scenario_hash
from .dsl.models import CompiledScenarioV2
from .engine2 import (
    EXECUTION_MODEL, MANIFEST2_CONTRACT, RESULT2_CONTRACT, Engine2Result,
    canonical_manifest2_bytes, canonical_result2_bytes, construct_result2,
    read_manifest2, read_result2,
)
from .ids import ID_VERSION
from .plugins import EMPTY_PLUGIN_REGISTRY, PluginError, PluginRegistry
from .resources import resolve_resources
from .rng import RNG_VERSION
from .schedule import (
    ENGINE2_EXECUTION_VERSION, SCHEDULE_CONTRACT, ScheduleArtifact,
    canonical_schedule_bytes, read_schedule,
)
from .scheduler import MAX_SCHEDULE_SEED, SCHEDULER_CONTRACT
from .values import canonical_bytes, normalize


CASE_CONTRACT = "scenario.engine2-case/1"
PLAN_CONTRACT = "scenario.engine2-suite-plan/1"
SUITE_CONTRACT = "scenario.engine2-suite/1"

MAX_SUITE_CASES = 64
MAX_CASE_INPUT_BYTES = 262_144
MAX_TOTAL_INPUT_BYTES = 4_194_304
MAX_CASE_REQUEST_BYTES = 524_288
MAX_TOTAL_REQUEST_BYTES = 1_048_576
MAX_INPUT_NESTING_DEPTH = 32
MAX_CASE_SELECTIONS = 65_536
MAX_TOTAL_SELECTIONS = 262_144
MAX_RETAINED_CHILD_BYTES = 67_108_864
MAX_CANONICAL_SUITE_BYTES = 2_097_152
MAX_ERROR_BYTES = 512
MAX_CASE_ID_BYTES = 128

_CASE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_CASE_STATUSES = frozenset({"SUCCESS", "EXPECTED_FAILURE", "UNEXPECTED_FAILURE", "ERROR"})
_EXPECTED_FAILURE_CODES = frozenset({"InvariantViolation"})
_ERROR_RECORDS = {
    ("preflight", "VALIDATION", "CASE_VALIDATION_FAILED"): "case validation failed",
    ("execution", "PLUGIN", "PLUGIN_EXECUTION_FAILED"): "trusted plugin execution failed",
    ("retention", "LIMIT", "CHILD_EVIDENCE_BOUND_EXCEEDED"): "retained child evidence bound exceeded",
    ("retention", "LIMIT", "SELECTION_BOUND_EXCEEDED"): "aggregate scheduler selection bound exceeded",
    ("execution", "INTERNAL", "INTERNAL_EXECUTION_FAILED"): "case execution failed",
}


class Engine2SuiteError(ValueError):
    """Stable fail-closed suite diagnostic without supplied-value reflection."""

    code = "ENGINE2_SUITE_INVALID"

    def __init__(self, field_name: str, message: str, *, code: str | None = None) -> None:
        self.field_name = field_name
        if code is not None:
            self.code = code
        super().__init__(f"{field_name}: {message}")


class Engine2SuiteBoundError(Engine2SuiteError):
    code = "ENGINE2_SUITE_BOUND_EXCEEDED"


class Engine2SuiteVerificationError(Engine2SuiteError):
    code = "ENGINE2_SUITE_VERIFICATION_FAILED"


def _hash(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _HASH.fullmatch(value) is None:
        raise Engine2SuiteError(field_name, "must be 64 lowercase hexadecimal characters")
    return value


def _integer(value: object, field_name: str, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise Engine2SuiteError(field_name, "must be a nonnegative integer excluding bool")
    if maximum is not None and value > maximum:
        raise Engine2SuiteBoundError(field_name, f"exceeds inclusive maximum {maximum}")
    return value


def _reference_clock(value: object, field_name: str) -> datetime:
    """Apply the native Engine 2 aware-datetime and UTC-normalization rule."""
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise Engine2SuiteError(field_name, "must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _freeze_inner(value: Any, *, field_name: str) -> Any:
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise Engine2SuiteError(field_name, "must use string mapping keys")
        return MappingProxyType({
            key: _freeze_inner(value[key], field_name=field_name) for key in sorted(value)
        })
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_inner(item, field_name=field_name) for item in value)
    return value


def _freeze(value: Any, *, field_name: str = "value") -> Any:
    # Bound recursive work before normalization or immutable materialization.
    _depth(value, field_name=field_name)
    try:
        normalize(value)
    except (TypeError, ValueError, RecursionError):
        raise Engine2SuiteError(field_name, "contains an unsupported semantic value") from None
    return _freeze_inner(value, field_name=field_name)


def _depth(
    value: Any,
    level: int = 0,
    *,
    maximum: int = MAX_INPUT_NESTING_DEPTH,
    field_name: str = "value",
) -> None:
    if level > maximum:
        raise Engine2SuiteBoundError(field_name, "exceeds maximum nesting depth")
    if isinstance(value, Mapping):
        for item in value.values():
            _depth(item, level + 1, maximum=maximum, field_name=field_name)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _depth(item, level + 1, maximum=maximum, field_name=field_name)


def _exact(value: object, fields: set[str], field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise Engine2SuiteError(field_name, "has missing or unknown fields")
    return value


def _plugin_versions(registry: PluginRegistry | None) -> Mapping[str, str]:
    if registry is None:
        return MappingProxyType({})
    if not isinstance(registry, PluginRegistry):
        raise Engine2SuiteError("plugins", "must be an explicit PluginRegistry or None")
    return MappingProxyType({plugin.name: plugin.version for plugin in registry})


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _limits_payload() -> Mapping[str, int]:
    return {
        "aggregate_input_bytes": MAX_TOTAL_INPUT_BYTES,
        "aggregate_selections": MAX_TOTAL_SELECTIONS,
        "canonical_suite_bytes": MAX_CANONICAL_SUITE_BYTES,
        "cases": MAX_SUITE_CASES,
        "error_bytes": MAX_ERROR_BYTES,
        "input_bytes_per_case": MAX_CASE_INPUT_BYTES,
        "request_bytes_per_case": MAX_CASE_REQUEST_BYTES,
        "request_bytes_total": MAX_TOTAL_REQUEST_BYTES,
        "retained_child_bytes": MAX_RETAINED_CHILD_BYTES,
        "selections_per_case": MAX_CASE_SELECTIONS,
    }


def _validate_resources_without_execution(scenario: CompiledScenarioV2, inputs: Mapping[str, Any] | None):
    """Resolve and validate deterministic resources without invoking a plugin."""
    from .dsl.actor_runtime import _generator_versions
    from .dsl.compiler import compile_constraint
    from .expressions import EvaluationEnvironment
    from .validation import ConstraintDefinitionError, ConstraintViolation, validate_resources

    if scenario.resources is not None:
        if inputs is not None:
            raise Engine2SuiteError("inputs", "must be absent for a scenario with pre-resolved resources")
        resources = scenario.resources
    else:
        resources = resolve_resources(scenario.document.resources, inputs)
    validate_resources(resources, scenario.document.validators)
    for item in scenario.document.constraints:
        result = compile_constraint(item["check"], resources).evaluate(EvaluationEnvironment({}, {}, {}))
        if type(result) is not bool:
            raise ConstraintDefinitionError("constraint check must return boolean")
        if not result:
            raise ConstraintViolation("constraint violated")
    return resources, _generator_versions(scenario.document)


def _validate_declared_plugins(scenario: CompiledScenarioV2, registry: PluginRegistry) -> None:
    for actor in scenario.document.actors:
        for sequence in (actor.steps, *actor.subflows.values()):
            for step in sequence:
                for declaration in step.generate.values():
                    if isinstance(declaration, Mapping) and "$plugin" in declaration:
                        body = declaration["$plugin"]
                        registry.require(body["name"], body["version"])


@dataclass(frozen=True, slots=True)
class Engine2CaseRequest:
    """One independently addressed Engine 2 operation."""

    case_id: str
    scenario: CompiledScenarioV2 = field(compare=False, repr=False)
    root_seed: str | int
    schedule_seed: int
    run_index: int = 0
    inputs: Mapping[str, Any] | None = field(default=None, compare=False, repr=False)
    plugins: PluginRegistry | None = field(default=None, compare=False, repr=False)
    expected_classification: str = "SUCCESS"
    expected_failure_code: str | None = None
    position: int = field(default=0, compare=False)
    coordinates: Mapping[str, Any] = field(init=False, compare=False, repr=False)
    case_identity: str = field(init=False)
    input_canonical_bytes: bytes = field(init=False, compare=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.case_id, str) or _CASE_ID.fullmatch(self.case_id) is None:
            raise Engine2SuiteError("case_id", "must be a portable ASCII label of at most 128 bytes")
        if len(self.case_id.encode("utf-8")) > MAX_CASE_ID_BYTES:
            raise Engine2SuiteBoundError("case_id", "exceeds MAX_CASE_ID_BYTES")
        if not isinstance(self.scenario, CompiledScenarioV2):
            raise Engine2SuiteError("scenario", "must be a validated CompiledScenarioV2")
        if isinstance(self.root_seed, bool) or not isinstance(self.root_seed, (str, int)):
            raise Engine2SuiteError("root_seed", "must be a string or integer excluding bool")
        _integer(self.schedule_seed, "schedule_seed", MAX_SCHEDULE_SEED)
        _integer(self.run_index, "run_index")
        _integer(self.position, "position")
        if self.expected_classification not in {"SUCCESS", "FAILED"}:
            raise Engine2SuiteError("expectation.classification", "must be SUCCESS or FAILED")
        if self.expected_classification == "SUCCESS":
            if self.expected_failure_code is not None:
                raise Engine2SuiteError("expectation.failure_code", "must be null for SUCCESS")
        elif not isinstance(self.expected_failure_code, str) or not self.expected_failure_code:
            raise Engine2SuiteError("expectation.failure_code", "must be a nonempty string for FAILED")

        frozen_inputs = None if self.inputs is None else _freeze(self.inputs, field_name="inputs")
        if frozen_inputs is not None and not isinstance(frozen_inputs, Mapping):
            raise Engine2SuiteError("inputs", "must be a string-keyed mapping or None")
        identity_inputs = MappingProxyType({}) if frozen_inputs is None else frozen_inputs
        _depth(identity_inputs, field_name="inputs")
        encoded_inputs = canonical_bytes(identity_inputs)
        if len(encoded_inputs) > MAX_CASE_INPUT_BYTES:
            raise Engine2SuiteBoundError("inputs", "exceeds MAX_CASE_INPUT_BYTES")
        versions = _plugin_versions(self.plugins)
        registry = EMPTY_PLUGIN_REGISTRY if self.plugins is None else self.plugins
        assert isinstance(registry, PluginRegistry)
        try:
            resources, generators = _validate_resources_without_execution(self.scenario, frozen_inputs)
            _validate_declared_plugins(self.scenario, registry)
        except Engine2SuiteError:
            raise
        except (PluginError, TypeError, ValueError):
            raise Engine2SuiteError("case", "preflight validation failed") from None

        coordinates = {
            "case_id": self.case_id,
            "contract": CASE_CONTRACT,
            "domain_pack_versions": {},
            "dsl_version": 2,
            "engine_version": ENGINE2_EXECUTION_VERSION,
            "execution_model": EXECUTION_MODEL,
            "expectation": {
                "classification": self.expected_classification,
                "failure_code": self.expected_failure_code,
            },
            "generator_versions": generators,
            "id_algorithm_version": ID_VERSION,
            "input_bytes": len(encoded_inputs),
            "input_hash": hashlib.sha256(encoded_inputs).hexdigest(),
            "input_resource_hashes": resources.hashes(),
            "locale": "C",
            "manifest_contract": MANIFEST2_CONTRACT,
            "plugin_versions": versions,
            "position": self.position,
            "reference_clock_start": self.scenario.reference_clock_start,
            "result_contract": RESULT2_CONTRACT,
            "rng_algorithm_version": RNG_VERSION,
            "root_seed": self.root_seed,
            "run_index": self.run_index,
            "scenario_hash": canonical_scenario_hash(self.scenario),
            "schedule_contract": SCHEDULE_CONTRACT,
            "schedule_seed": self.schedule_seed,
            "scheduler_contract": SCHEDULER_CONTRACT,
        }
        frozen_coordinates = _freeze(coordinates, field_name="coordinates")
        coordinate_bytes = canonical_bytes(frozen_coordinates)
        if len(coordinate_bytes) > MAX_CASE_REQUEST_BYTES:
            raise Engine2SuiteBoundError("coordinates", "exceeds MAX_CASE_REQUEST_BYTES")
        object.__setattr__(self, "inputs", frozen_inputs)
        object.__setattr__(self, "coordinates", frozen_coordinates)
        object.__setattr__(self, "case_identity", hashlib.sha256(coordinate_bytes).hexdigest())
        object.__setattr__(self, "input_canonical_bytes", encoded_inputs)


@dataclass(frozen=True, slots=True)
class Engine2SuitePlan:
    """A finite immutable sequence validated completely before execution."""

    cases: tuple[Engine2CaseRequest, ...]
    plan_hash: str = field(init=False)
    payload: Mapping[str, Any] = field(init=False, compare=False, repr=False)

    def __post_init__(self) -> None:
        if isinstance(self.cases, (str, bytes, Mapping, set, frozenset)) or not isinstance(self.cases, Sequence):
            raise Engine2SuiteError("cases", "must be an explicit ordered sequence")
        if not 1 <= len(self.cases) <= MAX_SUITE_CASES:
            raise Engine2SuiteBoundError("cases", f"must contain 1..{MAX_SUITE_CASES} requests")
        if not all(isinstance(item, Engine2CaseRequest) for item in self.cases):
            raise Engine2SuiteError("cases", "must contain Engine2CaseRequest values")
        positioned = tuple(replace(item, position=index) for index, item in enumerate(self.cases))
        ids = tuple(item.case_id for item in positioned)
        identities = tuple(item.case_identity for item in positioned)
        if len(ids) != len(set(ids)):
            raise Engine2SuiteError("cases", "contains a duplicate case_id")
        if len(identities) != len(set(identities)):
            raise Engine2SuiteError("cases", "contains a duplicate case identity")
        if sum(item.coordinates["input_bytes"] for item in positioned) > MAX_TOTAL_INPUT_BYTES:
            raise Engine2SuiteBoundError("cases", "exceeds MAX_TOTAL_INPUT_BYTES")
        if sum(len(canonical_bytes(item.coordinates)) for item in positioned) > MAX_TOTAL_REQUEST_BYTES:
            raise Engine2SuiteBoundError("cases", "exceeds MAX_TOTAL_REQUEST_BYTES")
        identity_payload = {
            "case_identities": identities,
            "contract": PLAN_CONTRACT,
            "limits": _limits_payload(),
        }
        digest = hashlib.sha256(canonical_bytes(identity_payload)).hexdigest()
        payload = _freeze({**identity_payload, "plan_hash": digest}, field_name="plan")
        object.__setattr__(self, "cases", positioned)
        object.__setattr__(self, "plan_hash", digest)
        object.__setattr__(self, "payload", payload)


@dataclass(frozen=True, slots=True)
class Engine2CaseOutcome:
    """One canonical ordered observation plus optional in-memory native children."""

    request: Mapping[str, Any]
    case_identity: str
    status: str
    observed: Mapping[str, Any]
    native: Mapping[str, Any] | None
    error: Mapping[str, Any] | None
    result: Engine2Result | None = field(default=None, compare=False, repr=False)
    schedule: ScheduleArtifact | None = field(default=None, compare=False, repr=False)

    def __post_init__(self) -> None:
        request = _validate_case_payload(self.request)
        digest = hashlib.sha256(canonical_bytes(request)).hexdigest()
        if _hash(self.case_identity, "case_identity") != digest:
            raise Engine2SuiteError("case_identity", "does not match request")
        if not isinstance(self.status, str) or self.status not in _CASE_STATUSES:
            raise Engine2SuiteError("status", "is unsupported")
        observed = _validate_observed(self.observed)
        native = None if self.native is None else _validate_native(self.native)
        error = None if self.error is None else _validate_error(self.error)
        if self.status == "ERROR":
            if native is not None or error is None or observed["classification"] is not None:
                raise Engine2SuiteError("case", "ERROR requires only a redacted error record")
        else:
            if native is None or error is not None or observed["classification"] not in {"SUCCESS", "FAILED"}:
                raise Engine2SuiteError("case", "completed status requires native evidence and observation")
            required_status = _completed_status(request["expectation"], observed)
            if self.status != required_status:
                raise Engine2SuiteError("status", "does not match observation and expectation")
        object.__setattr__(self, "request", _freeze(request))
        object.__setattr__(self, "observed", _freeze(observed))
        object.__setattr__(self, "native", None if native is None else _freeze(native))
        object.__setattr__(self, "error", None if error is None else _freeze(error))

    def payload(self) -> Mapping[str, Any]:
        return {
            "case_identity": self.case_identity,
            "error": self.error,
            "native": self.native,
            "observed": self.observed,
            "request": self.request,
            "status": self.status,
        }


@dataclass(frozen=True, slots=True)
class Engine2SuiteOutcome:
    """Strict canonical ordered suite aggregate."""

    plan: Mapping[str, Any]
    cases: tuple[Engine2CaseOutcome, ...]
    counts: Mapping[str, int]
    status: str
    aggregate_hash: str = ""
    contract: str = SUITE_CONTRACT

    def __post_init__(self) -> None:
        if self.contract != SUITE_CONTRACT:
            raise Engine2SuiteError("contract", "unsupported contract")
        plan = _validate_plan_payload(self.plan)
        cases = tuple(self.cases)
        if not 1 <= len(cases) <= MAX_SUITE_CASES or not all(isinstance(item, Engine2CaseOutcome) for item in cases):
            raise Engine2SuiteBoundError("cases", f"must contain 1..{MAX_SUITE_CASES} outcomes")
        identities = tuple(item.case_identity for item in cases)
        if identities != tuple(plan["case_identities"]):
            raise Engine2SuiteError("cases", "does not match ordered plan identities")
        ids: list[str] = []
        for position, item in enumerate(cases):
            if item.request["position"] != position:
                raise Engine2SuiteError("cases", "positions must equal list indexes")
            ids.append(item.request["case_id"])
        if len(ids) != len(set(ids)) or len(identities) != len(set(identities)):
            raise Engine2SuiteError("cases", "contains duplicate identities")
        if sum(item.request["input_bytes"] for item in cases) > MAX_TOTAL_INPUT_BYTES:
            raise Engine2SuiteBoundError("cases", "exceeds MAX_TOTAL_INPUT_BYTES")
        if sum(len(canonical_bytes(item.request)) for item in cases) > MAX_TOTAL_REQUEST_BYTES:
            raise Engine2SuiteBoundError("cases", "exceeds MAX_TOTAL_REQUEST_BYTES")
        retained_claim = sum(
            reference["size"]
            for item in cases if item.native is not None
            for reference in item.native.values()
        )
        if retained_claim > MAX_RETAINED_CHILD_BYTES:
            raise Engine2SuiteBoundError("cases", "claims excess retained child evidence")
        expected_counts = _counts(cases)
        if _validate_counts(self.counts) != expected_counts:
            raise Engine2SuiteError("counts", "does not match case statuses")
        expected_status = "SUCCESS" if not expected_counts["unexpected_failure"] and not expected_counts["error"] else "FAILED"
        if self.status != expected_status:
            raise Engine2SuiteError("status", "does not match case statuses")
        identity = {
            "cases": tuple(item.payload() for item in cases),
            "contract": self.contract,
            "counts": expected_counts,
            "plan": plan,
            "status": self.status,
        }
        digest = hashlib.sha256(canonical_bytes(identity)).hexdigest()
        if self.aggregate_hash and _hash(self.aggregate_hash, "aggregate_hash") != digest:
            raise Engine2SuiteError("aggregate_hash", "does not match suite identity")
        object.__setattr__(self, "plan", _freeze(plan))
        object.__setattr__(self, "cases", cases)
        object.__setattr__(self, "counts", MappingProxyType(expected_counts))
        object.__setattr__(self, "aggregate_hash", digest)
        if len(canonical_engine2_suite_bytes(self)) > MAX_CANONICAL_SUITE_BYTES:
            raise Engine2SuiteBoundError("suite", "exceeds MAX_CANONICAL_SUITE_BYTES")

    def identity_payload(self) -> Mapping[str, Any]:
        return {
            "cases": tuple(item.payload() for item in self.cases),
            "contract": self.contract,
            "counts": self.counts,
            "plan": self.plan,
            "status": self.status,
        }

    def payload(self) -> Mapping[str, Any]:
        return {**self.identity_payload(), "aggregate_hash": self.aggregate_hash}


_CASE_FIELDS = {
    "case_id", "contract", "domain_pack_versions", "dsl_version", "engine_version",
    "execution_model", "expectation", "generator_versions", "id_algorithm_version",
    "input_bytes", "input_hash", "input_resource_hashes", "locale", "manifest_contract",
    "plugin_versions", "position", "reference_clock_start", "result_contract",
    "rng_algorithm_version", "root_seed", "run_index", "scenario_hash", "schedule_contract",
    "schedule_seed", "scheduler_contract",
}


def _validate_case_payload(raw: object) -> Mapping[str, Any]:
    value = _exact(raw, _CASE_FIELDS, "request")
    if value["contract"] != CASE_CONTRACT:
        raise Engine2SuiteError("request.contract", "unsupported contract")
    if not isinstance(value["case_id"], str) or _CASE_ID.fullmatch(value["case_id"]) is None:
        raise Engine2SuiteError("request.case_id", "is invalid")
    if len(value["case_id"].encode("utf-8")) > MAX_CASE_ID_BYTES:
        raise Engine2SuiteBoundError("request.case_id", "exceeds MAX_CASE_ID_BYTES")
    for field_name in ("position", "run_index"):
        _integer(value[field_name], f"request.{field_name}")
    _integer(value["input_bytes"], "request.input_bytes", MAX_CASE_INPUT_BYTES)
    _integer(value["schedule_seed"], "request.schedule_seed", MAX_SCHEDULE_SEED)
    if isinstance(value["root_seed"], bool) or not isinstance(value["root_seed"], (str, int)):
        raise Engine2SuiteError("request.root_seed", "is invalid")
    for field_name in ("scenario_hash", "input_hash"):
        _hash(value[field_name], f"request.{field_name}")
    expected_constants = {
        "domain_pack_versions": {}, "dsl_version": 2, "engine_version": ENGINE2_EXECUTION_VERSION,
        "execution_model": EXECUTION_MODEL, "id_algorithm_version": ID_VERSION, "locale": "C",
        "manifest_contract": MANIFEST2_CONTRACT, "result_contract": RESULT2_CONTRACT,
        "rng_algorithm_version": RNG_VERSION, "schedule_contract": SCHEDULE_CONTRACT,
        "scheduler_contract": SCHEDULER_CONTRACT,
    }
    for field_name, expected in expected_constants.items():
        if value[field_name] != expected or (field_name == "dsl_version" and isinstance(value[field_name], bool)):
            raise Engine2SuiteError(f"request.{field_name}", "unsupported compatibility coordinate")
    for field_name in ("input_resource_hashes", "plugin_versions", "generator_versions"):
        mapping = value[field_name]
        if not isinstance(mapping, Mapping) or not all(isinstance(k, str) and isinstance(v, str) for k, v in mapping.items()):
            raise Engine2SuiteError(f"request.{field_name}", "must map strings to strings")
    for resource_name, resource_hash in value["input_resource_hashes"].items():
        _hash(resource_hash, f"request.input_resource_hashes.{resource_name}")
    for key, version in value["generator_versions"].items():
        if key.startswith("plugin:") and value["plugin_versions"].get(key.removeprefix("plugin:")) != version:
            raise Engine2SuiteError("request.plugin_versions", "does not satisfy generator requirements")
    expectation = _exact(value["expectation"], {"classification", "failure_code"}, "expectation")
    if expectation["classification"] == "SUCCESS":
        if expectation["failure_code"] is not None:
            raise Engine2SuiteError("expectation", "SUCCESS requires null failure_code")
    elif expectation["classification"] == "FAILED":
        if not isinstance(expectation["failure_code"], str) or not expectation["failure_code"]:
            raise Engine2SuiteError("expectation", "FAILED requires a failure_code")
    else:
        raise Engine2SuiteError("expectation", "classification is unsupported")
    checked = {**value, "reference_clock_start": _reference_clock(
        value["reference_clock_start"], "request.reference_clock_start",
    )}
    if len(canonical_bytes(checked)) > MAX_CASE_REQUEST_BYTES:
        raise Engine2SuiteBoundError("request", "exceeds MAX_CASE_REQUEST_BYTES")
    return checked


def _validate_plan_payload(raw: object) -> Mapping[str, Any]:
    value = _exact(raw, {"case_identities", "contract", "limits", "plan_hash"}, "plan")
    if value["contract"] != PLAN_CONTRACT:
        raise Engine2SuiteError("plan.contract", "unsupported contract")
    if not isinstance(value["case_identities"], (tuple, list)) or not 1 <= len(value["case_identities"]) <= MAX_SUITE_CASES:
        raise Engine2SuiteBoundError("plan.case_identities", "must be a bounded ordered list")
    identities = tuple(_hash(item, "plan.case_identities") for item in value["case_identities"])
    if len(identities) != len(set(identities)):
        raise Engine2SuiteError("plan.case_identities", "contains a duplicate")
    expected_limits = _limits_payload()
    limits = _exact(value["limits"], set(expected_limits), "plan.limits")
    for field_name, expected in expected_limits.items():
        if _integer(limits[field_name], f"plan.limits.{field_name}") != expected:
            raise Engine2SuiteError("plan.limits", "unsupported limits")
    if dict(limits) != dict(expected_limits):
        raise Engine2SuiteError("plan.limits", "unsupported limits")
    payload = {"case_identities": identities, "contract": PLAN_CONTRACT, "limits": _limits_payload()}
    digest = hashlib.sha256(canonical_bytes(payload)).hexdigest()
    if _hash(value["plan_hash"], "plan.plan_hash") != digest:
        raise Engine2SuiteError("plan.plan_hash", "does not match plan identity")
    return {**payload, "plan_hash": digest}


def _validate_observed(raw: object) -> Mapping[str, Any]:
    value = _exact(raw, {"classification", "failure_code"}, "observed")
    if value["classification"] is None:
        if value["failure_code"] is not None:
            raise Engine2SuiteError("observed", "null classification requires null failure_code")
    elif value["classification"] == "SUCCESS":
        if value["failure_code"] is not None:
            raise Engine2SuiteError("observed", "SUCCESS requires null failure_code")
    elif value["classification"] == "FAILED":
        if not isinstance(value["failure_code"], str) or not value["failure_code"]:
            raise Engine2SuiteError("observed", "FAILED requires a failure_code")
    else:
        raise Engine2SuiteError("observed.classification", "is unsupported")
    return value


def _completed_status(expectation: Mapping[str, Any], observed: Mapping[str, Any]) -> str:
    if observed["classification"] == "SUCCESS" and expectation["classification"] == "SUCCESS":
        return "SUCCESS"
    if (
        observed["classification"] == "FAILED"
        and expectation["classification"] == "FAILED"
        and observed["failure_code"] == expectation["failure_code"]
        and observed["failure_code"] in _EXPECTED_FAILURE_CODES
    ):
        return "EXPECTED_FAILURE"
    return "UNEXPECTED_FAILURE"


def _validate_reference(raw: object, expected_contract: str, field_name: str) -> Mapping[str, Any]:
    value = _exact(raw, {"contract", "identity", "sha256", "size"}, field_name)
    if value["contract"] != expected_contract:
        raise Engine2SuiteError(f"{field_name}.contract", "is incompatible")
    _hash(value["identity"], f"{field_name}.identity")
    _hash(value["sha256"], f"{field_name}.sha256")
    _integer(value["size"], f"{field_name}.size", MAX_RETAINED_CHILD_BYTES)
    return value


def _validate_native(raw: object) -> Mapping[str, Any]:
    value = _exact(raw, {"manifest", "result", "schedule"}, "native")
    return {
        "manifest": _validate_reference(value["manifest"], MANIFEST2_CONTRACT, "native.manifest"),
        "result": _validate_reference(value["result"], RESULT2_CONTRACT, "native.result"),
        "schedule": _validate_reference(value["schedule"], SCHEDULE_CONTRACT, "native.schedule"),
    }


def _validate_error(raw: object) -> Mapping[str, Any]:
    value = _exact(raw, {"code", "family", "message", "stage"}, "error")
    if not all(isinstance(value[field_name], str) for field_name in ("stage", "family", "code", "message")):
        raise Engine2SuiteError("error", "is not a supported stage/family/code/message record")
    key = (value["stage"], value["family"], value["code"])
    if key not in _ERROR_RECORDS or value["message"] != _ERROR_RECORDS[key]:
        raise Engine2SuiteError("error", "is not a supported stage/family/code/message record")
    if len(canonical_bytes(value)) > MAX_ERROR_BYTES:
        raise Engine2SuiteBoundError("error", "exceeds MAX_ERROR_BYTES")
    return value


def _reference(contract: str, identity: str, data: bytes) -> Mapping[str, Any]:
    return {
        "contract": contract, "identity": identity,
        "sha256": hashlib.sha256(data).hexdigest(), "size": len(data),
    }


def _native(result: Engine2Result, schedule: ScheduleArtifact) -> tuple[Mapping[str, Any], int]:
    result_bytes = canonical_result2_bytes(result)
    manifest_bytes = canonical_manifest2_bytes(result.manifest)
    schedule_bytes = canonical_schedule_bytes(schedule)
    native = {
        "manifest": _reference(MANIFEST2_CONTRACT, result.manifest.manifest_hash, manifest_bytes),
        "result": _reference(RESULT2_CONTRACT, result.result_hash, result_bytes),
        "schedule": _reference(SCHEDULE_CONTRACT, schedule.schedule_hash, schedule_bytes),
    }
    return native, len(result_bytes) + len(manifest_bytes) + len(schedule_bytes)


def _error(stage: str, family: str, code: str) -> Mapping[str, str]:
    key = (stage, family, code)
    try:
        message = _ERROR_RECORDS[key]
    except KeyError:
        raise Engine2SuiteError("error", "is not produced by the suite executor") from None
    return {"code": code, "family": family, "message": message, "stage": stage}


def _error_outcome(request: Engine2CaseRequest, stage: str, family: str, code: str) -> Engine2CaseOutcome:
    return Engine2CaseOutcome(
        request.coordinates, request.case_identity, "ERROR",
        {"classification": None, "failure_code": None}, None, _error(stage, family, code),
    )


def _authoritative_failed_outcome(error: Exception) -> Any | None:
    from .dsl.actor_runtime import ActorExecutionOutcome
    outcome = getattr(error, "internal_outcome", None)
    if not isinstance(outcome, ActorExecutionOutcome) or not isinstance(outcome.schedule, ScheduleArtifact):
        return None
    schedule = outcome.schedule
    if outcome.classification != "FAILED" or schedule.classification != "FAILED" or schedule.failure is None:
        return None
    if not schedule.records or schedule.records[-1].outcome != "FAILED":
        return None
    if schedule.failure.code != getattr(error, "code", type(error).__name__):
        return None
    if getattr(error, "actor_address", None) != schedule.failure.actor:
        return None
    return outcome


def _execute_case(request: Engine2CaseRequest) -> tuple[Engine2Result | None, ScheduleArtifact | None, str, Mapping[str, Any] | None]:
    from .engine2 import execute_engine2
    from .invariants import InvariantViolation

    try:
        result, schedule = execute_engine2(
            request.scenario, request.root_seed, request.schedule_seed,
            run_index=request.run_index,
            inputs=None if request.inputs is None else _thaw(request.inputs),
            plugins=request.plugins,
        )
    except Exception as error:
        # Plugin exceptions may carry an actor-runtime outcome, but trusted
        # plugin execution is not a recognized deterministic business failure
        # and can never satisfy an expected-failure declaration.
        if isinstance(error, PluginError):
            return None, None, "ERROR", _error("execution", "PLUGIN", "PLUGIN_EXECUTION_FAILED")
        outcome = _authoritative_failed_outcome(error)
        if outcome is not None:
            result = construct_result2(request.scenario, outcome)
            schedule = outcome.schedule
            expected = (
                isinstance(error, InvariantViolation)
                and request.expected_classification == "FAILED"
                and request.expected_failure_code == result.failure.code
                and result.failure.code in _EXPECTED_FAILURE_CODES
            )
            return result, schedule, "EXPECTED_FAILURE" if expected else "UNEXPECTED_FAILURE", None
        return None, None, "ERROR", _error("execution", "INTERNAL", "INTERNAL_EXECUTION_FAILED")
    status = "SUCCESS" if request.expected_classification == "SUCCESS" else "UNEXPECTED_FAILURE"
    return result, schedule, status, None


def execute_engine2_suite(plan: Engine2SuitePlan) -> Engine2SuiteOutcome:
    """Execute a completely prevalidated plan serially in exact request order."""
    if not isinstance(plan, Engine2SuitePlan):
        raise TypeError("plan must be Engine2SuitePlan")
    retained = 0
    selections = 0
    outcomes: list[Engine2CaseOutcome] = []
    for request in plan.cases:
        result, schedule, status, error = _execute_case(request)
        if result is None or schedule is None:
            outcomes.append(Engine2CaseOutcome(
                request.coordinates, request.case_identity, status,
                {"classification": None, "failure_code": None}, None, error,
            ))
            continue
        if len(schedule.records) > MAX_CASE_SELECTIONS or selections + len(schedule.records) > MAX_TOTAL_SELECTIONS:
            outcomes.append(_error_outcome(request, "retention", "LIMIT", "SELECTION_BOUND_EXCEEDED"))
            continue
        native, child_bytes = _native(result, schedule)
        if retained + child_bytes > MAX_RETAINED_CHILD_BYTES:
            outcomes.append(_error_outcome(request, "retention", "LIMIT", "CHILD_EVIDENCE_BOUND_EXCEEDED"))
            continue
        selections += len(schedule.records)
        retained += child_bytes
        failure_code = None if result.failure is None else result.failure.code
        outcomes.append(Engine2CaseOutcome(
            request.coordinates, request.case_identity, status,
            {"classification": result.classification, "failure_code": failure_code},
            native, None, result, schedule,
        ))
    records = tuple(outcomes)
    counts = _counts(records)
    overall = "SUCCESS" if not counts["unexpected_failure"] and not counts["error"] else "FAILED"
    return Engine2SuiteOutcome(plan.payload, records, counts, overall)


def _counts(cases: Sequence[Engine2CaseOutcome]) -> dict[str, int]:
    return {
        "error": sum(item.status == "ERROR" for item in cases),
        "expected_failure": sum(item.status == "EXPECTED_FAILURE" for item in cases),
        "success": sum(item.status == "SUCCESS" for item in cases),
        "total": len(cases),
        "unexpected_failure": sum(item.status == "UNEXPECTED_FAILURE" for item in cases),
    }


def _validate_counts(raw: object) -> dict[str, int]:
    fields = {"error", "expected_failure", "success", "total", "unexpected_failure"}
    value = _exact(raw, fields, "counts")
    return {field_name: _integer(value[field_name], f"counts.{field_name}") for field_name in fields}


def canonical_engine2_suite_identity_bytes(suite: Engine2SuiteOutcome) -> bytes:
    if not isinstance(suite, Engine2SuiteOutcome):
        raise TypeError("suite must be Engine2SuiteOutcome")
    encoded = canonical_bytes(suite.identity_payload())
    if len(encoded) > MAX_CANONICAL_SUITE_BYTES:
        raise Engine2SuiteBoundError("suite", "exceeds MAX_CANONICAL_SUITE_BYTES")
    return encoded


def canonical_engine2_suite_bytes(suite: Engine2SuiteOutcome) -> bytes:
    if not isinstance(suite, Engine2SuiteOutcome):
        raise TypeError("suite must be Engine2SuiteOutcome")
    encoded = canonical_bytes(suite.payload())
    if len(encoded) > MAX_CANONICAL_SUITE_BYTES:
        raise Engine2SuiteBoundError("suite", "exceeds MAX_CANONICAL_SUITE_BYTES")
    return encoded


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise Engine2SuiteError("json", "contains a duplicate key")
        result[key] = value
    return result


def _semantic(value: Any) -> Any:
    if isinstance(value, list):
        return tuple(_semantic(item) for item in value)
    if not isinstance(value, Mapping):
        return value
    if set(value) == {"$type", "value"} and value["$type"] == "datetime" and isinstance(value["value"], str):
        try:
            parsed = datetime.fromisoformat(value["value"])
        except ValueError:
            raise Engine2SuiteError("datetime", "is malformed") from None
        if parsed.tzinfo is None or parsed.utcoffset() is None or canonical_bytes(parsed) != canonical_bytes(value):
            raise Engine2SuiteError("datetime", "is not canonical")
        return parsed
    return {key: _semantic(item) for key, item in value.items()}


def read_engine2_suite(source: bytes | str) -> Engine2SuiteOutcome:
    """Strictly read bounded canonical suite bytes without executing anything."""
    if not isinstance(source, (bytes, str)):
        raise TypeError("source must be bytes or str")
    data = source if isinstance(source, bytes) else source.encode("utf-8")
    if len(data) > MAX_CANONICAL_SUITE_BYTES:
        raise Engine2SuiteBoundError("suite", "exceeds MAX_CANONICAL_SUITE_BYTES")
    try:
        raw = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_object,
                         parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except Engine2SuiteError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError):
        raise Engine2SuiteError("json", "must be strict UTF-8 JSON") from None
    _depth(raw, field_name="json")
    top = _exact(raw, {"aggregate_hash", "cases", "contract", "counts", "plan", "status"}, "suite")
    if not isinstance(top["cases"], list) or len(top["cases"]) > MAX_SUITE_CASES:
        raise Engine2SuiteBoundError("cases", "must be a bounded list")
    cases = []
    fields = {"case_identity", "error", "native", "observed", "request", "status"}
    for index, raw_case in enumerate(top["cases"]):
        item = _exact(raw_case, fields, f"cases[{index}]")
        cases.append(Engine2CaseOutcome(
            _semantic(item["request"]), item["case_identity"], item["status"],
            item["observed"], item["native"], item["error"],
        ))
    suite = Engine2SuiteOutcome(
        top["plan"], tuple(cases), top["counts"], top["status"],
        top["aggregate_hash"], top["contract"],
    )
    if canonical_engine2_suite_bytes(suite) != data:
        raise Engine2SuiteError("suite", "must be canonical JSON bytes")
    return suite


def _child_bytes(
    suite: Engine2SuiteOutcome,
    supplied: Mapping[str, Mapping[str, bytes]] | None,
    case: Engine2CaseOutcome,
) -> Mapping[str, bytes]:
    case_id = case.request["case_id"]
    if supplied is not None:
        try:
            children = supplied[case_id]
        except (KeyError, TypeError):
            raise Engine2SuiteVerificationError("child_evidence", "is missing required case evidence") from None
        if not isinstance(children, Mapping) or set(children) != {"manifest", "result", "schedule"}:
            raise Engine2SuiteVerificationError("child_evidence", "has missing or unknown artifact names")
        if not all(isinstance(item, bytes) for item in children.values()):
            raise Engine2SuiteVerificationError("child_evidence", "must contain bytes")
        return children
    if case.result is None or case.schedule is None:
        raise Engine2SuiteVerificationError("child_evidence", "must be supplied for a read suite")
    return {
        "manifest": canonical_manifest2_bytes(case.result.manifest),
        "result": canonical_result2_bytes(case.result),
        "schedule": canonical_schedule_bytes(case.schedule),
    }


def _verify_reference(reference: Mapping[str, Any], data: bytes, field_name: str) -> None:
    if len(data) != reference["size"] or hashlib.sha256(data).hexdigest() != reference["sha256"]:
        raise Engine2SuiteVerificationError(field_name, "exact child bytes do not match reference")


def verify_engine2_suite(
    suite: Engine2SuiteOutcome | bytes | str,
    child_evidence: Mapping[str, Mapping[str, bytes]] | None = None,
) -> Engine2SuiteOutcome:
    """Verify aggregate and native links offline; never execute scenarios/plugins."""
    evidence = suite if isinstance(suite, Engine2SuiteOutcome) else read_engine2_suite(suite)
    # Reconstructing performs an independent aggregate validation even for an object.
    checked = read_engine2_suite(canonical_engine2_suite_bytes(evidence))
    completed_ids = {item.request["case_id"] for item in evidence.cases if item.native is not None}
    if child_evidence is not None:
        if not isinstance(child_evidence, Mapping) or set(child_evidence) != completed_ids:
            raise Engine2SuiteVerificationError("child_evidence", "case set does not match completed suite cases")
    retained = 0
    selections = 0
    seen_exact: dict[str, bytes] = {}
    for case in evidence.cases:
        if case.native is None:
            continue
        children = _child_bytes(evidence, child_evidence, case)
        for name, data in children.items():
            retained += len(data)
            if retained > MAX_RETAINED_CHILD_BYTES:
                raise Engine2SuiteBoundError("child_evidence", "exceeds MAX_RETAINED_CHILD_BYTES")
            digest = hashlib.sha256(data).hexdigest()
            previous = seen_exact.get(digest)
            if previous is not None and previous != data:
                raise Engine2SuiteVerificationError("child_evidence", "SHA-256 collision detected")
            seen_exact[digest] = data
            _verify_reference(case.native[name], data, f"{case.request['case_id']}.{name}")
        manifest = read_manifest2(children["manifest"])
        result = read_result2(children["result"])
        schedule = read_schedule(children["schedule"])
        if (
            manifest.manifest_hash != case.native["manifest"]["identity"]
            or result.result_hash != case.native["result"]["identity"]
            or schedule.schedule_hash != case.native["schedule"]["identity"]
        ):
            raise Engine2SuiteVerificationError("native.identity", "does not match parsed child")
        if result.manifest != manifest:
            raise Engine2SuiteVerificationError("native.manifest", "does not equal Result/2 manifest")
        request = case.request
        checks = (
            (request["scenario_hash"], manifest.scenario_hash),
            (dict(request["input_resource_hashes"]), dict(manifest.input_resource_hashes)),
            (request["root_seed"], manifest.root_seed),
            (request["schedule_seed"], manifest.schedule_seed),
            (request["run_index"], manifest.run_index),
            (request["reference_clock_start"], manifest.reference_clock_start),
            (dict(request["generator_versions"]), dict(manifest.generator_versions)),
            (manifest.scenario_hash, schedule.scenario_hash),
            (dict(manifest.input_resource_hashes), dict(schedule.input_resource_hashes)),
            (manifest.root_seed, schedule.execution.root_seed),
            (manifest.schedule_seed, schedule.schedule_seed),
            (manifest.run_index, schedule.run_index),
            (manifest.reference_clock_start, schedule.execution.reference_clock_start),
            (dict(manifest.generator_versions), dict(schedule.execution.generator_versions)),
            (manifest.engine_version, schedule.execution.engine_version),
            (manifest.dsl_version, schedule.execution.dsl_version),
            (result.schedule_reference.schedule_hash, schedule.schedule_hash),
            (result.schedule_reference.scenario_hash, schedule.scenario_hash),
            (result.classification, schedule.classification),
        )
        if any(expected != received for expected, received in checks):
            raise Engine2SuiteVerificationError("native.linkage", "child coordinates do not match")
        result_code = None if result.failure is None else result.failure.code
        schedule_code = None if schedule.failure is None else schedule.failure.code
        if result_code != schedule_code or result.classification != case.observed["classification"] or result_code != case.observed["failure_code"]:
            raise Engine2SuiteVerificationError("native.failure", "classification or failure code does not match")
        selections += len(schedule.records)
        if len(schedule.records) > MAX_CASE_SELECTIONS or selections > MAX_TOTAL_SELECTIONS:
            raise Engine2SuiteBoundError("native.selections", "exceeds suite selection bounds")
    return checked


__all__ = (
    "CASE_CONTRACT", "PLAN_CONTRACT", "SUITE_CONTRACT",
    "Engine2CaseOutcome", "Engine2CaseRequest", "Engine2SuiteBoundError",
    "Engine2SuiteError", "Engine2SuiteOutcome", "Engine2SuitePlan",
    "Engine2SuiteVerificationError", "canonical_engine2_suite_bytes",
    "canonical_engine2_suite_identity_bytes", "execute_engine2_suite",
    "read_engine2_suite", "verify_engine2_suite",
)
