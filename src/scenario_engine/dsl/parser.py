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
_TOP_KEYS = _REQUIRED_TOP_KEYS | {"resources", "validators", "constraints", "subflows", "invariants", "faults", "oracle"}
_STEP_KEYS = {"id", "generate", "derive", "write", "emit", "advance", "transition"}
_NODE_KEYS = _STEP_KEYS | {"call", "branch", "repeat"}
_EXPRESSION_OPERATORS = {
    "$state", "$local", "$derived", "$literal", "$add", "$mul", "$append",
    "$object", "$sum_field", "$resource", "$sub", "$div", "$eq", "$ne",
    "$lt", "$lte", "$gt", "$gte", "$and", "$or", "$not", "$len", "$scope",
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
                         constraint: bool = False, control: bool = False) -> None:
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
    if control and operator in {"$local", "$derived"}:
        _fail(path, f"{operator} is not allowed at a control boundary")
    if operator in {"$state", "$local", "$derived", "$resource", "$scope"}:
        _symbol(payload, path + "." + operator)
        if operator == "$scope" and any(not segment for segment in payload.split(".")):
            _fail(path + ".$scope", "invalid dot-separated path")
    elif operator == "$literal":
        decode_semantic_value(payload, path + ".$literal")
    elif operator in {"$add", "$mul", "$sub", "$div", "$eq", "$ne", "$lt", "$lte", "$gt", "$gte"}:
        if not isinstance(payload, list) or len(payload) != 2:
            _fail(path + "." + operator, "expected exactly two expressions")
        for index, child in enumerate(payload):
            _validate_expression(child, f"{path}.{operator}[{index}]", emission=emission, constraint=constraint, control=control)
    elif operator in {"$and", "$or"}:
        if not isinstance(payload, list) or not payload:
            _fail(path + "." + operator, "expected one or more expressions")
        for index, child in enumerate(payload):
            _validate_expression(child, f"{path}.{operator}[{index}]", constraint=constraint, control=control)
    elif operator in {"$not", "$len"}:
        _validate_expression(payload, path + "." + operator, constraint=constraint, control=control)
    elif operator == "$append":
        body = _mapping(payload, path + ".$append")
        _only_keys(body, {"list", "value"}, path + ".$append")
        if set(body) != {"list", "value"}:
            _fail(path + ".$append", "list and value are required")
        _validate_expression(body["list"], path + ".$append.list", emission=emission, control=control)
        _validate_expression(body["value"], path + ".$append.value", emission=emission, control=control)
    elif operator == "$object":
        body = _mapping(payload, path + ".$object")
        for name, child in body.items():
            _symbol(name, path + ".$object key")
            _validate_expression(child, f"{path}.$object.{name}", emission=emission, control=control)
    elif operator == "$sum_field":
        body = _mapping(payload, path + ".$sum_field")
        _only_keys(body, {"source", "field"}, path + ".$sum_field")
        if set(body) != {"source", "field"}:
            _fail(path + ".$sum_field", "source and field are required")
        _validate_expression(body["source"], path + ".$sum_field.source", emission=emission, control=control)
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

def _parse_invariants(value):
    if not isinstance(value, list): _fail("$.invariants", "expected ordered list")
    result, seen = [], set()
    for index, raw in enumerate(value):
        path=f"$.invariants[{index}]"; item=_mapping(raw,path); _only_keys(item,{"id","check"},path)
        if set(item)!={"id","check"}: _fail(path,"id and check are required")
        _symbol(item["id"],path+".id")
        if item["id"] in seen: _fail(path+".id",f"duplicate invariant ID {item['id']}")
        seen.add(item["id"]); _validate_expression(item["check"],path+".check")
        def refs(node):
            if isinstance(node, Mapping): return set(node)&{"$local","$derived","$scope"} | set().union(*(refs(v) for v in node.values()))
            if isinstance(node,list): return set().union(*(refs(v) for v in node))
            return set()
        forbidden=refs(item["check"])
        if forbidden: _fail(path+".check",f"{sorted(forbidden)[0]} is not allowed in invariants")
        result.append(MappingProxyType(dict(item)))
    return tuple(result)

def _id_list(value,path):
    if not isinstance(value,list) or any(not isinstance(x,str) or not x for x in value): _fail(path,"expected list of non-empty IDs")
    return tuple(value)

def _expect(value,path):
    body=_mapping(value,path); _only_keys(body,{"constraints","invariants"},path)
    return MappingProxyType({"constraints":_id_list(body.get("constraints",[]),path+".constraints"),"invariants":_id_list(body.get("invariants",[]),path+".invariants")})

def _parse_faults(value, steps):
    if not isinstance(value,list): _fail("$.faults","expected ordered list")
    executable={s.step_id:s for s in steps if s.control_kind is None}; result=[]; seen=set()
    for index,raw in enumerate(value):
        path=f"$.faults[{index}]"; item=_mapping(raw,path); _only_keys(item,{"id","enabled","at","selector","operator","expect","strict_unexpected"},path)
        if not {"id","at","operator"}<=set(item): _fail(path,"id, at, and operator are required")
        _symbol(item["id"],path+".id")
        if item["id"] in seen: _fail(path+".id","duplicate fault ID")
        seen.add(item["id"]); enabled=item.get("enabled",False); strict=item.get("strict_unexpected",True)
        if type(enabled) is not bool or type(strict) is not bool: _fail(path,"enabled and strict_unexpected must be boolean")
        at=item["at"]
        if at not in {"before_validation","before_step"}: _fail(path+".at","unsupported fault hook")
        op=_mapping(item["operator"],path+".operator")
        if len(op)!=1: _fail(path+".operator","exactly one operator required")
        name,body=next(iter(op.items())); allowed={"before_validation":{"override_resource"},"before_step":{"override_write","override_local","suppress_emissions"}}[at]
        if name not in allowed: _fail(path+".operator","unsupported operator at hook")
        parsed={"id":item["id"],"enabled":enabled,"at":at,"operator":MappingProxyType(dict(op)),"expect":_expect(item.get("expect",{}),path+".expect"),"strict_unexpected":strict}
        if at=="before_step":
            selector=_mapping(item.get("selector"),path+".selector"); _only_keys(selector,{"step","subflow_path","repetition_indexes"},path+".selector")
            step=selector.get("step"); _symbol(step,path+".selector.step")
            if step not in executable: _fail(path+".selector.step",f"unknown executable step {step}")
            if "subflow_path" in selector and (not isinstance(selector["subflow_path"],list) or any(not isinstance(x,str) or not x for x in selector["subflow_path"])): _fail(path+".selector.subflow_path","expected control-node ID list")
            if "repetition_indexes" in selector and (not isinstance(selector["repetition_indexes"],list) or any(type(x) is not int or x<0 for x in selector["repetition_indexes"])): _fail(path+".selector.repetition_indexes","expected nonnegative integer list")
            body=_mapping(body,path+f".operator.{name}") if name!="suppress_emissions" else body
            if name=="override_write":
                _only_keys(body,{"path","value"},path); target=body.get("path")
                if target not in executable[step].write: _fail(path,"override_write target is not declared by step")
                _validate_expression(body["value"],path+".value",control=True)
            elif name=="override_local":
                _only_keys(body,{"name","value"},path); target=body.get("name")
                if target not in executable[step].generate: _fail(path,"override_local target is not generated by step")
                _validate_expression(body["value"],path+".value",control=True)
            elif body is not True: _fail(path,"suppress_emissions requires true")
            parsed["selector"]=MappingProxyType({k:tuple(v) if isinstance(v,list) else v for k,v in selector.items()})
        else:
            body=_mapping(body,path+".operator.override_resource"); _only_keys(body,{"path","value"},path)
            _symbol(body.get("path"),path+".path"); _validate_expression(body["value"],path+".value",constraint=True)
        result.append(MappingProxyType(parsed))
    return tuple(result)

def _parse_oracle(value):
    if value is None: return None
    body=_mapping(value,"$.oracle"); _only_keys(body,{"expected","strict_unexpected"},"$.oracle")
    strict=body.get("strict_unexpected",True)
    if type(strict) is not bool: _fail("$.oracle.strict_unexpected","expected boolean")
    return MappingProxyType({"expected":_expect(body.get("expected",{}),"$.oracle.expected"),"strict_unexpected":strict})


def _with(value: Any, path: str) -> Mapping[str, Any]:
    bindings = _mapping(value, path)
    for name, expression in bindings.items():
        _symbol(name, path + " key")
        _validate_expression(expression, f"{path}.{name}", control=True)
    return MappingProxyType(dict(bindings))


def _target(value: Any, path: str) -> Mapping[str, Any]:
    target = _mapping(value, path)
    _only_keys(target, {"subflow", "with"}, path)
    if "subflow" not in target:
        _fail(path, "subflow is required")
    _symbol(target["subflow"], path + ".subflow")
    return MappingProxyType({"subflow": target["subflow"], "with": _with(target.get("with", {}), path + ".with")})


def _parse_node(raw: Any, path: str, seen: set[str]) -> StepDocument:
    node = _mapping(raw, path)
    _only_keys(node, _NODE_KEYS, path)
    if "id" not in node or "transition" not in node:
        _fail(path, "id and transition are required")
    step_id = node["id"]
    _symbol(step_id, path + ".id")
    if step_id in seen:
        _fail(path + ".id", f"duplicate step ID {step_id} (global node ID)")
    seen.add(step_id)
    controls = [kind for kind in ("call", "branch", "repeat") if kind in node]
    executable = any(key in node for key in ("generate", "derive", "write", "emit", "advance"))
    if len(controls) > 1 or (controls and executable):
        _fail(path, "node must be exactly one executable, call, branch, or repeat node")
    transition = node["transition"]
    if transition is not None:
        _symbol(transition, path + ".transition")
    if controls:
        kind = controls[0]
        body = _mapping(node[kind], path + "." + kind)
        if kind == "call":
            parsed = _target(body, path + ".call")
        elif kind == "branch":
            _only_keys(body, {"cases", "else"}, path + ".branch")
            cases_raw = body.get("cases")
            if not isinstance(cases_raw, list) or not cases_raw:
                _fail(path + ".branch.cases", "expected non-empty ordered list")
            cases = []
            for index, raw_case in enumerate(cases_raw):
                case_path = f"{path}.branch.cases[{index}]"
                case = _mapping(raw_case, case_path)
                _only_keys(case, {"when", "subflow", "with"}, case_path)
                if not {"when", "subflow"} <= set(case):
                    _fail(case_path, "when and subflow are required")
                _validate_expression(case["when"], case_path + ".when", control=True)
                target = _target({key: case[key] for key in case if key != "when"}, case_path)
                cases.append(MappingProxyType({"when": case["when"], **target}))
            parsed_dict: dict[str, Any] = {"cases": tuple(cases)}
            if "else" in body:
                parsed_dict["else"] = _target(body["else"], path + ".branch.else")
            parsed = MappingProxyType(parsed_dict)
        else:
            _only_keys(body, {"count", "max", "subflow", "with", "index_as"}, path + ".repeat")
            if not {"count", "max", "subflow"} <= set(body):
                _fail(path + ".repeat", "count, max, and subflow are required")
            _validate_expression(body["count"], path + ".repeat.count", control=True)
            maximum = body["max"]
            if isinstance(maximum, bool) or not isinstance(maximum, int) or not 0 <= maximum <= 100:
                _fail(path + ".repeat.max", "expected literal integer from 0 through 100")
            target = _target({key: body[key] for key in ("subflow", "with") if key in body}, path + ".repeat")
            parsed_dict = {"count": body["count"], "max": maximum, **target}
            if "index_as" in body:
                _symbol(body["index_as"], path + ".repeat.index_as")
                if body["index_as"] in target["with"]:
                    _fail(path + ".repeat.index_as", "collides with explicit with binding")
                parsed_dict["index_as"] = body["index_as"]
            parsed = MappingProxyType(parsed_dict)
        empty = MappingProxyType({})
        return StepDocument(step_id, empty, empty, empty, (), timedelta(0), transition,
                            parsed if kind == "call" else None,
                            parsed if kind == "branch" else None,
                            parsed if kind == "repeat" else None)
    generate = _mapping(node.get("generate", {}), path + ".generate")
    derive = _mapping(node.get("derive", {}), path + ".derive")
    write = _mapping(node.get("write", {}), path + ".write")
    for section_name, section, validator in (("generate", generate, _validate_generator), ("derive", derive, _validate_expression), ("write", write, _validate_expression)):
        for name, expression in section.items():
            _symbol(name, f"{path}.{section_name} key")
            validator(expression, f"{path}.{section_name}.{name}")
    emit_raw = node.get("emit", [])
    if not isinstance(emit_raw, list):
        _fail(path + ".emit", "expected ordered list")
    emissions = []
    for index, raw_emission in enumerate(emit_raw):
        emit_path = f"{path}.emit[{index}]"; emission = _mapping(raw_emission, emit_path)
        _only_keys(emission, {"type", "fields"}, emit_path)
        if set(emission) != {"type", "fields"}: _fail(emit_path, "type and fields are required")
        _symbol(emission["type"], emit_path + ".type"); fields = _mapping(emission["fields"], emit_path + ".fields")
        for name, expression in fields.items():
            _symbol(name, emit_path + ".fields key"); _validate_expression(expression, f"{emit_path}.fields.{name}", emission=True)
        emissions.append(MappingProxyType({"type": emission["type"], "fields": MappingProxyType(dict(fields))}))
    advance = _mapping(node.get("advance", {"seconds": 0}), path + ".advance")
    _only_keys(advance, {"seconds"}, path + ".advance")
    seconds = advance.get("seconds")
    if isinstance(seconds, bool) or not isinstance(seconds, int) or seconds < 0: _fail(path + ".advance.seconds", "expected nonnegative integer")
    return StepDocument(step_id, MappingProxyType(dict(generate)), MappingProxyType(dict(derive)), MappingProxyType(dict(write)), tuple(emissions), timedelta(seconds=seconds), transition)


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
    if not isinstance(steps_raw, list) or not steps_raw: _fail("$.steps", "expected non-empty ordered list")
    seen: set[str] = set()
    steps = [_parse_node(raw, f"$.steps[{index}]", seen) for index, raw in enumerate(steps_raw)]
    subflows_raw = _mapping(root.get("subflows", {}), "$.subflows")
    if "subflows" in root and not subflows_raw: _fail("$.subflows", "declared subflow mapping must be non-empty")
    subflows: dict[str, tuple[StepDocument, ...]] = {}
    for name, raw_subflow in subflows_raw.items():
        _symbol(name, "$.subflows key")
        definition = _mapping(raw_subflow, f"$.subflows.{name}")
        _only_keys(definition, {"steps"}, f"$.subflows.{name}")
        body = definition.get("steps")
        if not isinstance(body, list) or not body: _fail(f"$.subflows.{name}.steps", "expected non-empty ordered list")
        subflows[name] = tuple(_parse_node(raw, f"$.subflows.{name}.steps[{index}]", seen) for index, raw in enumerate(body))
    all_steps=tuple(steps)+tuple(step for flow in subflows.values() for step in flow)
    invariants=_parse_invariants(root.get("invariants",[]))
    faults=_parse_faults(root.get("faults",[]),all_steps)
    oracle=_parse_oracle(root.get("oracle"))
    return ScenarioDocument(1, scenario_id, reference, MappingProxyType(dict(initial)), tuple(steps),
                            MappingProxyType(resources), validators, constraints, MappingProxyType(subflows), invariants, faults, oracle)


def parse_yaml_file(path: str | Path) -> ScenarioDocument:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise DSLParseError(f"unable to read YAML document: {error}") from None
    return parse_yaml(text)
