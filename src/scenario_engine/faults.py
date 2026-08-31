"""Declarative deterministic Phase 0.5 fault operators."""
from dataclasses import replace
from types import MappingProxyType
from .dsl.compiler import LiteralGenerator, compile_expression

class FaultError(ValueError): pass
class FaultDefinitionError(FaultError): pass
class FaultApplicationError(FaultError): pass

def matches(fault, address, step_id, subflow_path=()):
    selector = fault.get("selector", {})
    return (selector.get("step") == step_id
        and ("subflow_path" not in selector or tuple(selector["subflow_path"]) == tuple(subflow_path))
        and ("repetition_indexes" not in selector or tuple(selector["repetition_indexes"]) == tuple(address.repetition_indexes)))

def apply_step_faults(spec, faults, address, state, resources, scope, subflow_path=()):
    applied = []
    for fault in faults:
        if not fault["enabled"] or fault["at"] != "before_step" or not matches(fault, address, spec.step_id, subflow_path): continue
        name, body = next(iter(fault["operator"].items()))
        if name == "override_write":
            patch = dict(spec.state_patch); patch[body["path"]] = compile_expression(body["value"], resources, scope)
            spec = replace(spec, state_patch=MappingProxyType(patch))
        elif name == "override_local":
            value = compile_expression(body["value"], resources, scope).evaluate(__import__('scenario_engine.expressions', fromlist=['EvaluationEnvironment']).EvaluationEnvironment(state, {}, {}, scope))
            generators = dict(spec.generators); generators[body["name"]] = LiteralGenerator(value)
            spec = replace(spec, generators=MappingProxyType(generators))
        elif name == "suppress_emissions":
            spec = replace(spec, emit=lambda context, post, locals_, derived: ())
        applied.append(fault)
    if applied:
        original = spec.history_builder
        ids = tuple(f["id"] for f in applied)
        spec = replace(spec, history_builder=lambda **kw: original(**{**kw, "faults_applied": ids}))
    return spec, tuple(applied)
