from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from scenario_engine.artifacts import GeneratedArtifact
from scenario_engine.context import GenerationContext
from scenario_engine.expressions import (
    Add, Append, BooleanMany, BooleanNot, DerivedRef, Divide, Equal, Expression,
    GreaterThan, GreaterThanOrEqual, Length, LessThan, LessThanOrEqual, Literal,
    LocalRef, Multiply, NotEqual, Record, ScopeRef, StateRef, Subtract, SumField,
)
from scenario_engine.runner import StepSpec
from scenario_engine.expressions import resolve_semantic_path

from .errors import DSLCompilationError
from .models import CompiledScenario, CompiledStep, ScenarioDocument
from .parser import decode_semantic_value


@dataclass(frozen=True, slots=True)
class LogicalIDGenerator:
    slot: str

    def generate(self, context: GenerationContext) -> Any:
        return context.logical_id(self.slot)


@dataclass(frozen=True, slots=True)
class LiteralGenerator:
    value: Any

    def generate(self, context: GenerationContext) -> Any:
        return self.value


@dataclass(frozen=True, slots=True)
class IntegerGenerator:
    minimum: int
    maximum: int

    def generate(self, context: GenerationContext) -> int:
        return context.rng().inclusive_int(self.minimum, self.maximum)


def _expression(node: Mapping[str, Any], resources=None, scope=None) -> Expression:
    operator, payload = next(iter(node.items()))
    if operator == "$state":
        return StateRef(payload)
    if operator == "$local":
        return LocalRef(payload)
    if operator == "$derived":
        return DerivedRef(payload)
    if operator == "$literal":
        return Literal(decode_semantic_value(payload))
    if operator == "$resource":
        if resources is None:
            return Literal(payload)  # replaced before execution during preparation
        return Literal(resources.lookup(payload))
    if operator == "$scope":
        return ScopeRef(payload) if scope is None else Literal(resolve_semantic_path(scope, payload))
    if operator == "$add":
        return Add(_expression(payload[0], resources, scope), _expression(payload[1], resources, scope))
    if operator == "$mul":
        return Multiply(_expression(payload[0], resources, scope), _expression(payload[1], resources, scope))
    binary = {"$sub": Subtract, "$div": Divide, "$eq": Equal, "$ne": NotEqual,
              "$lt": LessThan, "$lte": LessThanOrEqual, "$gt": GreaterThan,
              "$gte": GreaterThanOrEqual}
    if operator in binary:
        return binary[operator](_expression(payload[0], resources, scope), _expression(payload[1], resources, scope))
    if operator in {"$and", "$or"}:
        return BooleanMany(tuple(_expression(child, resources, scope) for child in payload), operator == "$and")
    if operator == "$not": return BooleanNot(_expression(payload, resources, scope))
    if operator == "$len": return Length(_expression(payload, resources, scope))
    if operator == "$append":
        return Append(_expression(payload["list"], resources, scope), _expression(payload["value"], resources, scope))
    if operator == "$object":
        return Record(MappingProxyType({name: _expression(child, resources, scope) for name, child in payload.items()}))
    if operator == "$sum_field":
        return SumField(_expression(payload["source"], resources, scope), payload["field"])
    raise AssertionError("validated expression operator was not compiled")


def _generator(node: Mapping[str, Any]) -> Any:
    operator, payload = next(iter(node.items()))
    if operator == "$int":
        return IntegerGenerator(payload[0], payload[1])
    if operator == "$id":
        return LogicalIDGenerator(payload)
    if operator == "$literal":
        return LiteralGenerator(decode_semantic_value(payload))
    raise AssertionError("validated generator operator was not compiled")


def _emitter(declarations: tuple[Mapping[str, Any], ...], resources=None, scope=None):
    compiled = tuple((declaration["type"], {
        name: _expression(node, resources, scope) for name, node in declaration["fields"].items()
    }) for declaration in declarations)

    def emit(context, post_state, locals_, derived):
        from scenario_engine.expressions import EvaluationEnvironment

        env = EvaluationEnvironment(post_state, MappingProxyType({}), MappingProxyType({}))
        artifacts = []
        for index, (artifact_type, fields) in enumerate(compiled):
            address = context.address.child("emit", str(index), artifact_type)
            value = {name: fields[name].evaluate(env) for name in sorted(fields)}
            artifacts.append(GeneratedArtifact(
                artifact_type, artifact_type, value,
                context.ids.derive(address, "artifact"), address,
            ))
        return tuple(artifacts)

    return emit


def _validate_sequence(steps, path):
    ids = [step.step_id for step in steps]
    known = set(ids)
    for index, step in enumerate(steps):
        expected = ids[index + 1] if index + 1 < len(ids) else None
        if step.transition is not None and step.transition not in known:
            raise DSLCompilationError(
                f"{path}[{index}].transition: unknown node ID {step.transition}"
            )
        if step.transition != expected:
            if expected is None:
                message = "final step transition must be null"
            elif step.transition is None:
                message = f"non-final step transition must be {expected}"
            else:
                message = f"linear transition must target immediately following step {expected}"
            raise DSLCompilationError(f"{path}[{index}].transition: {message}")


def _targets(step):
    if step.call is not None: return (step.call["subflow"],)
    if step.repeat is not None: return (step.repeat["subflow"],)
    if step.branch is not None:
        result = [case["subflow"] for case in step.branch["cases"]]
        if "else" in step.branch: result.append(step.branch["else"]["subflow"])
        return tuple(result)
    return ()


def _validate_control(document):
    from scenario_engine.control_flow import SubflowCycleError, UnknownSubflowError
    known = set(document.subflows)
    for sequence_name, steps in (("$", document.steps), *sorted(document.subflows.items())):
        for step in steps:
            for target in _targets(step):
                if target not in known: raise UnknownSubflowError(f"{step.step_id}: unknown subflow {target}")
    graph = {name: sorted({target for step in steps for target in _targets(step)}) for name, steps in document.subflows.items()}
    visiting, complete = [], set()
    def visit(name):
        if name in visiting:
            cycle = visiting[visiting.index(name):] + [name]
            raise SubflowCycleError("subflow call cycle: " + " -> ".join(cycle))
        if name in complete: return
        visiting.append(name)
        for child in graph[name]: visit(child)
        visiting.pop(); complete.add(name)
    for name in sorted(graph): visit(name)


def _compile_step(step, resources, scope=None):
    if step.control_kind is not None:
        return step
    transition = step.transition
    spec = StepSpec(
        step.step_id,
        MappingProxyType({name: _generator(node) for name, node in step.generate.items()}),
        MappingProxyType({name: _expression(node, resources, scope) for name, node in step.derive.items()}),
        MappingProxyType({name: _expression(node, resources, scope) for name, node in step.write.items()}),
        step.advance, emit=_emitter(step.emit, resources, scope), transition=lambda state, target=transition: target,
    )
    return CompiledStep(spec, transition)


def compile_document(document: ScenarioDocument, resources=None) -> CompiledScenario:
    _validate_sequence(document.steps, "$.steps")
    for name, steps in document.subflows.items(): _validate_sequence(steps, f"$.subflows.{name}.steps")
    _validate_control(document)
    compiled: list[Any] = []
    for step in document.steps:
        compiled.append(_compile_step(step, resources))
    subflows = MappingProxyType({name: tuple(_compile_step(step, resources) for step in steps) for name, steps in document.subflows.items()})
    return CompiledScenario(
        document.scenario_id, document.reference_clock_start, document.initial_state,
        tuple(compiled), compiled[0].step_id, document, resources, subflows,
    )


def compile_constraint(node: Mapping[str, Any], resources) -> Expression:
    return _expression(node, resources)


def compile_expression(node: Mapping[str, Any], resources, scope=None) -> Expression:
    return _expression(node, resources, scope)


def compile_scoped_sequence(steps, resources, scope):
    return tuple(_compile_step(step, resources, scope) for step in steps)
