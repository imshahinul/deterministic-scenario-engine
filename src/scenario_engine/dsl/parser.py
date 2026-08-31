from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

import yaml

from scenario_engine.values import MISSING, normalize

from .errors import DSLParseError, DSLSchemaError, UnsupportedDSLVersionError
from .models import ScenarioDocument, StepDocument


_REQUIRED_TOP_KEYS = {"dsl_version", "scenario", "clock", "initial_state", "steps"}
_TOP_KEYS = _REQUIRED_TOP_KEYS | {"resources", "validators", "constraints"}
_STEP_KEYS = {"id", "generate", "derive", "write", "emit", "advance", "transition"}
_EXPRESSION_OPERATORS = {
    "$state", "$local", "$derived", "$literal", "$add", "$mul", "$append",
    "$object", "$sum_field", "$resource", "$sub", "$div", "$eq", "$ne",
    "$lt", "$lte", "$gt", "$gte", "$and", "$or", "$not", "$len",
}
_GENERATOR_OPERATORS = {"$int", "$id", "$literal"}


def _fail(path: str, message: str) -> None:
    raise DSLSchemaError(f"{path}: {message}")


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(path, "expected mapping")
    if not all(isinstance(key, str) for key in value):
        _fail(path, "mapping keys must be strings")
    return value


def _only_keys(value: Mapping[str, Any], allowed: set[str], path: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        _fail(path, "unknown key(s): " + ", ".join(unknown))


def decode_semantic_value(value: Any, path: str = "value") -> Any:
    if isinstance(value, float):
        _fail(path, "Python float semantic values are forbidden; use $decimal")
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, list):
        return [decode_semantic_value(item, f"{path}[{index}]") for index, item in enumerate(value)]
    if isinstance(value, Mapping):
        mapping = _mapping(value, path)
        wrapper_keys = [key for key in mapping if key.startswith("$")]
        if wrapper_keys:
            if len(mapping) != 1 or len(wrapper_keys) != 1:
                _fail(path, "typed semantic wrapper must have exactly one key")
            operator, payload = next(iter(mapping.items()))
            if operator == "$decimal":
                if not isinstance(payload, str) or not payload:
                    _fail(path, "$decimal requires a non-empty string")
                try:
                    result = Decimal(payload)
                except InvalidOperation:
                    _fail(path, "invalid decimal string")
                if not result.is_finite():
                    _fail(path, "$decimal must be finite")
                return result
            if operator == "$datetime":
                return _parse_datetime(payload, path + ".$datetime")
            if operator == "$duration":
                duration = _mapping(payload, path + ".$duration")
                _only_keys(duration, {"seconds"}, path + ".$duration")
                if set(duration) != {"seconds"}:
                    _fail(path + ".$duration", "seconds is required")
                seconds = duration["seconds"]
                if isinstance(seconds, bool) or not isinstance(seconds, int):
                    _fail(path + ".$duration.seconds", "expected integer")
                return timedelta(seconds=seconds)
            if operator == "$missing":
                if payload is not True:
                    _fail(path + ".$missing", "expected true")
                return MISSING
            _fail(path, f"unknown semantic wrapper {operator}")
        return {key: decode_semantic_value(item, f"{path}.{key}") for key, item in mapping.items()}
    _fail(path, f"unsupported YAML value {type(value).__name__}")


def _parse_datetime(value: Any, path: str) -> datetime:
    if not isinstance(value, str) or not value:
        _fail(path, "expected ISO-8601 string")
    text = value[:-1] + "+00:00" if value.endswith(("Z", "z")) else value
    try:
        result = datetime.fromisoformat(text)
    except ValueError:
        _fail(path, "invalid ISO-8601 datetime")
    if result.tzinfo is None or result.utcoffset() is None:
        _fail(path, "datetime must be timezone-aware")
    return result.astimezone(timezone.utc)


def _symbol(value: Any, path: str) -> None:
    if not isinstance(value, str) or not value:
        _fail(path, "expected non-empty top-level symbolic name")


def _validate_expression(node: Any, path: str, *, emission: bool = False,
                         constraint: bool = False) -> None:
    mapping = _mapping(node, path)
    if len(mapping) != 1:
        _fail(path, "expression must contain exactly one operator")
    operator, payload = next(iter(mapping.items()))
    if operator not in _EXPRESSION_OPERATORS:
        _fail(path, f"unknown expression operator {operator}")
    if emission and operator not in {"$state", "$literal", "$resource"}:
        _fail(path, f"{operator} is not allowed in emission fields")
    if constraint and operator in {"$state", "$local", "$derived"}:
        _fail(path, f"{operator} is not allowed in constraints")
    if operator in {"$state", "$local", "$derived", "$resource"}:
        _symbol(payload, path + "." + operator)
    elif operator == "$literal":
        decode_semantic_value(payload, path + ".$literal")
    elif operator in {"$add", "$mul", "$sub", "$div", "$eq", "$ne", "$lt", "$lte", "$gt", "$gte"}:
        if not isinstance(payload, list) or len(payload) != 2:
            _fail(path + "." + operator, "expected exactly two expressions")
        for index, child in enumerate(payload):
            _validate_expression(child, f"{path}.{operator}[{index}]", emission=emission, constraint=constraint)
    elif operator in {"$and", "$or"}:
        if not isinstance(payload, list) or not payload:
            _fail(path + "." + operator, "expected one or more expressions")
        for index, child in enumerate(payload):
            _validate_expression(child, f"{path}.{operator}[{index}]", constraint=constraint)
    elif operator in {"$not", "$len"}:
        _validate_expression(payload, path + "." + operator, constraint=constraint)
    elif operator == "$append":
        body = _mapping(payload, path + ".$append")
        _only_keys(body, {"list", "value"}, path + ".$append")
        if set(body) != {"list", "value"}:
            _fail(path + ".$append", "list and value are required")
        _validate_expression(body["list"], path + ".$append.list", emission=emission)
        _validate_expression(body["value"], path + ".$append.value", emission=emission)
    elif operator == "$object":
        body = _mapping(payload, path + ".$object")
        for name, child in body.items():
            _symbol(name, path + ".$object key")
            _validate_expression(child, f"{path}.$object.{name}", emission=emission)
    elif operator == "$sum_field":
        body = _mapping(payload, path + ".$sum_field")
        _only_keys(body, {"source", "field"}, path + ".$sum_field")
        if set(body) != {"source", "field"}:
            _fail(path + ".$sum_field", "source and field are required")
        _validate_expression(body["source"], path + ".$sum_field.source", emission=emission)
        _symbol(body["field"], path + ".$sum_field.field")


def _validate_generator(node: Any, path: str) -> None:
    mapping = _mapping(node, path)
    if len(mapping) != 1:
        _fail(path, "generator must contain exactly one operator")
    operator, payload = next(iter(mapping.items()))
    if operator not in _GENERATOR_OPERATORS:
        _fail(path, f"unknown generator operator {operator}")
    if operator == "$int":
        if not isinstance(payload, list) or len(payload) != 2:
            _fail(path + ".$int", "expected exactly two inclusive bounds")
        if any(isinstance(bound, bool) or not isinstance(bound, int) for bound in payload):
            _fail(path + ".$int", "bounds must be integers, not booleans")
        if payload[0] > payload[1]:
            _fail(path + ".$int", "lower bound must not exceed upper bound")
    elif operator == "$id":
        _symbol(payload, path + ".$id")
    else:
        decode_semantic_value(payload, path + ".$literal")


def _decode_resource(value: Any, path: str) -> Any:
    if isinstance(value, Mapping):
        mapping = _mapping(value, path)
        operators = [key for key in mapping if key.startswith("$")]
        if operators:
            if len(mapping) != 1:
                _fail(path, "resource operator/wrapper must contain exactly one key")
            operator, payload = next(iter(mapping.items()))
            if operator in {"$input", "$ref"}:
                _symbol(payload, path + "." + operator)
                if any(not segment for segment in payload.split(".")):
                    _fail(path + "." + operator, "invalid dot-separated path")
                return MappingProxyType({operator: payload})
            if operator == "$literal":
                return decode_semantic_value(payload, path + ".$literal")
            return decode_semantic_value(mapping, path)
        return MappingProxyType({key: _decode_resource(mapping[key], f"{path}.{key}") for key in mapping})
    if isinstance(value, list):
        return tuple(_decode_resource(item, f"{path}[{index}]") for index, item in enumerate(value))
    return decode_semantic_value(value, path)


def _parse_validators(value: Any) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, list):
        _fail("$.validators", "expected ordered list")
    result: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    type_names = {"integer", "decimal", "boolean", "string", "null", "datetime",
                  "duration", "logical_id", "list", "map", "missing"}
    for index, raw in enumerate(value):
        path = f"$.validators[{index}]"; item = _mapping(raw, path)
        base = {"id", "resource", "kind"}
        if not base <= set(item): _fail(path, "id, resource, and kind are required")
        _symbol(item["id"], path + ".id"); _symbol(item["resource"], path + ".resource")
        if item["id"] in seen: _fail(path + ".id", f"duplicate validator ID {item['id']}")
        seen.add(item["id"]); kind = item["kind"]
        if kind not in {"required", "type", "range", "length", "one_of"}:
            _fail(path + ".kind", "unknown validator kind")
        allowed = base | ({"type"} if kind == "type" else {"min", "max"} if kind in {"range", "length"} else {"values"} if kind == "one_of" else set())
        _only_keys(item, allowed, path)
        parsed = dict(item)
        if kind == "type":
            parsed["type"] = "null" if item.get("type") is None else item.get("type")
            if parsed["type"] not in type_names: _fail(path + ".type", "unsupported semantic type")
        if kind in {"range", "length"}:
            if not ({"min", "max"} & set(item)): _fail(path, "at least one bound is required")
            for bound in {"min", "max"} & set(item):
                parsed[bound] = decode_semantic_value(item[bound], path + "." + bound)
                valid = type(parsed[bound]) in ((int, Decimal) if kind == "range" else (int,))
                if not valid or (kind == "length" and parsed[bound] < 0): _fail(path + "." + bound, "invalid bound")
            if "min" in parsed and "max" in parsed and Decimal(parsed["min"]) > Decimal(parsed["max"]): _fail(path, "minimum exceeds maximum")
        if kind == "one_of":
            if not isinstance(item.get("values"), list) or not item["values"]: _fail(path + ".values", "expected non-empty list")
            parsed["values"] = tuple(decode_semantic_value(candidate, path + ".values") for candidate in item["values"])
        result.append(MappingProxyType(parsed))
    return tuple(result)


def _parse_constraints(value: Any) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, list): _fail("$.constraints", "expected ordered list")
    result: list[Mapping[str, Any]] = []; seen: set[str] = set()
    for index, raw in enumerate(value):
        path = f"$.constraints[{index}]"; item = _mapping(raw, path)
        _only_keys(item, {"id", "check", "message"}, path)
        if not {"id", "check"} <= set(item): _fail(path, "id and check are required")
        _symbol(item["id"], path + ".id")
        if item["id"] in seen: _fail(path + ".id", f"duplicate constraint ID {item['id']}")
        seen.add(item["id"])
        if "message" in item and not isinstance(item["message"], str): _fail(path + ".message", "expected string")
        _validate_expression(item["check"], path + ".check", constraint=True)
        result.append(MappingProxyType(dict(item)))
    return tuple(result)


def parse_yaml(text: str) -> ScenarioDocument:
    try:
        loaded = yaml.safe_load(text)
    except yaml.YAMLError as error:
        mark = getattr(error, "problem_mark", None)
        location = f" at line {mark.line + 1}, column {mark.column + 1}" if mark else ""
        raise DSLParseError(f"YAML safe-load failed{location}") from None
    root = _mapping(loaded, "$")
    _only_keys(root, _TOP_KEYS, "$")
    missing = sorted(_REQUIRED_TOP_KEYS - set(root))
    if missing:
        _fail("$", "missing required key(s): " + ", ".join(missing))
    version = root["dsl_version"]
    if isinstance(version, bool) or not isinstance(version, int) or version != 1:
        raise UnsupportedDSLVersionError("$.dsl_version: supported version is integer 1")
    scenario_id = root["scenario"]
    _symbol(scenario_id, "$.scenario")
    clock = _mapping(root["clock"], "$.clock")
    _only_keys(clock, {"start"}, "$.clock")
    if set(clock) != {"start"}:
        _fail("$.clock", "start is required")
    reference = _parse_datetime(clock["start"], "$.clock.start")
    initial_raw = _mapping(root["initial_state"], "$.initial_state")
    initial = decode_semantic_value(initial_raw, "$.initial_state")
    try:
        normalize(initial)
    except (TypeError, ValueError) as error:
        _fail("$.initial_state", str(error))
    resources_raw = _mapping(root.get("resources", {}), "$.resources")
    if "resources" in root and not resources_raw:
        _fail("$.resources", "declared resource mapping must be non-empty")
    resources: dict[str, Any] = {}
    for name, raw_resource in resources_raw.items():
        _symbol(name, "$.resources key")
        resources[name] = _decode_resource(raw_resource, f"$.resources.{name}")
    validators = _parse_validators(root.get("validators", []))
    if "constraints" in root and not root["constraints"]:
        _fail("$.constraints", "declared constraint list must be non-empty")
    constraints = _parse_constraints(root.get("constraints", []))
    steps_raw = root["steps"]
    if not isinstance(steps_raw, list) or not steps_raw:
        _fail("$.steps", "expected non-empty ordered list")
    steps: list[StepDocument] = []
    seen: set[str] = set()
    for index, raw in enumerate(steps_raw):
        path = f"$.steps[{index}]"
        step = _mapping(raw, path)
        _only_keys(step, _STEP_KEYS, path)
        if "id" not in step or "transition" not in step:
            _fail(path, "id and transition are required")
        step_id = step["id"]
        _symbol(step_id, path + ".id")
        if step_id in seen:
            _fail(path + ".id", f"duplicate step ID {step_id}")
        seen.add(step_id)
        generate = _mapping(step.get("generate", {}), path + ".generate")
        derive = _mapping(step.get("derive", {}), path + ".derive")
        write = _mapping(step.get("write", {}), path + ".write")
        for section_name, section, validator in (
            ("generate", generate, _validate_generator),
            ("derive", derive, _validate_expression),
            ("write", write, _validate_expression),
        ):
            for name, node in section.items():
                _symbol(name, f"{path}.{section_name} key")
                validator(node, f"{path}.{section_name}.{name}")
        emit_raw = step.get("emit", [])
        if not isinstance(emit_raw, list):
            _fail(path + ".emit", "expected ordered list")
        emissions: list[Mapping[str, Any]] = []
        for emit_index, raw_emission in enumerate(emit_raw):
            emit_path = f"{path}.emit[{emit_index}]"
            emission = _mapping(raw_emission, emit_path)
            _only_keys(emission, {"type", "fields"}, emit_path)
            if set(emission) != {"type", "fields"}:
                _fail(emit_path, "type and fields are required")
            _symbol(emission["type"], emit_path + ".type")
            fields = _mapping(emission["fields"], emit_path + ".fields")
            for name, node in fields.items():
                _symbol(name, emit_path + ".fields key")
                _validate_expression(node, f"{emit_path}.fields.{name}", emission=True)
            emissions.append(MappingProxyType({"type": emission["type"], "fields": MappingProxyType(dict(fields))}))
        advance_raw = _mapping(step.get("advance", {"seconds": 0}), path + ".advance")
        _only_keys(advance_raw, {"seconds"}, path + ".advance")
        if set(advance_raw) != {"seconds"}:
            _fail(path + ".advance", "seconds is required")
        seconds = advance_raw["seconds"]
        if isinstance(seconds, bool) or not isinstance(seconds, int) or seconds < 0:
            _fail(path + ".advance.seconds", "expected nonnegative integer")
        transition = step["transition"]
        if transition is not None:
            _symbol(transition, path + ".transition")
        steps.append(StepDocument(
            step_id, MappingProxyType(dict(generate)), MappingProxyType(dict(derive)),
            MappingProxyType(dict(write)), tuple(emissions), timedelta(seconds=seconds), transition,
        ))
    return ScenarioDocument(1, scenario_id, reference, MappingProxyType(dict(initial)), tuple(steps),
                            MappingProxyType(resources), validators, constraints)


def parse_yaml_file(path: str | Path) -> ScenarioDocument:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise DSLParseError(f"unable to read YAML document: {error}") from None
    return parse_yaml(text)
