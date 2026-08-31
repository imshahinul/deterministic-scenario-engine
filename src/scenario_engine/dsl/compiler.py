from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from scenario_engine.artifacts import GeneratedArtifact
from scenario_engine.context import GenerationContext
from scenario_engine.expressions import (
    Add, Append, DerivedRef, Expression, Literal, LocalRef, Multiply, Record,
    StateRef, SumField,
)
from scenario_engine.runner import StepSpec

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


def _expression(node: Mapping[str, Any]) -> Expression:
    operator, payload = next(iter(node.items()))
    if operator == "$state":
        return StateRef(payload)
    if operator == "$local":
        return LocalRef(payload)
    if operator == "$derived":
        return DerivedRef(payload)
    if operator == "$literal":
        return Literal(decode_semantic_value(payload))
    if operator == "$add":
        return Add(_expression(payload[0]), _expression(payload[1]))
    if operator == "$mul":
        return Multiply(_expression(payload[0]), _expression(payload[1]))
    if operator == "$append":
        return Append(_expression(payload["list"]), _expression(payload["value"]))
    if operator == "$object":
        return Record(MappingProxyType({name: _expression(child) for name, child in payload.items()}))
    if operator == "$sum_field":
        return SumField(_expression(payload["source"]), payload["field"])
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


def _emitter(declarations: tuple[Mapping[str, Any], ...]):
    compiled = tuple((declaration["type"], {
        name: _expression(node) for name, node in declaration["fields"].items()
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


def compile_document(document: ScenarioDocument) -> CompiledScenario:
    ids = [step.step_id for step in document.steps]
    known = set(ids)
    for index, step in enumerate(document.steps):
        expected = ids[index + 1] if index + 1 < len(ids) else None
        if step.transition is not None and step.transition not in known:
            raise DSLCompilationError(
                f"$.steps[{index}].transition: unknown step ID {step.transition}"
            )
        if step.transition != expected:
            if expected is None:
                message = "final step transition must be null"
            elif step.transition is None:
                message = f"non-final step transition must be {expected}"
            else:
                message = f"linear transition must target immediately following step {expected}"
            raise DSLCompilationError(f"$.steps[{index}].transition: {message}")
    compiled: list[CompiledStep] = []
    for step in document.steps:
        transition = step.transition
        spec = StepSpec(
            step.step_id,
            MappingProxyType({name: _generator(node) for name, node in step.generate.items()}),
            MappingProxyType({name: _expression(node) for name, node in step.derive.items()}),
            MappingProxyType({name: _expression(node) for name, node in step.write.items()}),
            step.advance,
            emit=_emitter(step.emit),
            transition=lambda state, target=transition: target,
        )
        compiled.append(CompiledStep(spec, transition))
    return CompiledScenario(
        document.scenario_id, document.reference_clock_start, document.initial_state,
        tuple(compiled), compiled[0].step_id, document,
    )
