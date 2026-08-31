from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class EvaluationEnvironment:
    pre_state: Mapping[str, Any]
    locals: Mapping[str, Any]
    derived: Mapping[str, Any]


class Expression:
    def evaluate(self, env: EvaluationEnvironment) -> Any:
        raise NotImplementedError

    def dependencies(self) -> frozenset[str]:
        return frozenset()


@dataclass(frozen=True, slots=True)
class Literal(Expression):
    value: Any
    def evaluate(self, env: EvaluationEnvironment) -> Any:
        return self.value


@dataclass(frozen=True, slots=True)
class StateRef(Expression):
    name: str
    def evaluate(self, env: EvaluationEnvironment) -> Any:
        return env.pre_state[self.name]


@dataclass(frozen=True, slots=True)
class LocalRef(Expression):
    name: str
    def evaluate(self, env: EvaluationEnvironment) -> Any:
        return env.locals[self.name]


@dataclass(frozen=True, slots=True)
class DerivedRef(Expression):
    name: str
    def evaluate(self, env: EvaluationEnvironment) -> Any:
        return env.derived[self.name]
    def dependencies(self) -> frozenset[str]:
        return frozenset((self.name,))


@dataclass(frozen=True, slots=True)
class Binary(Expression):
    left: Expression
    right: Expression
    def dependencies(self) -> frozenset[str]:
        return self.left.dependencies() | self.right.dependencies()


class Add(Binary):
    def evaluate(self, env: EvaluationEnvironment) -> Any:
        return self.left.evaluate(env) + self.right.evaluate(env)


class Multiply(Binary):
    def evaluate(self, env: EvaluationEnvironment) -> Any:
        return self.left.evaluate(env) * self.right.evaluate(env)


@dataclass(frozen=True, slots=True)
class Append(Expression):
    sequence: Expression
    item: Expression
    def evaluate(self, env: EvaluationEnvironment) -> list[Any]:
        return list(self.sequence.evaluate(env)) + [self.item.evaluate(env)]
    def dependencies(self) -> frozenset[str]:
        return self.sequence.dependencies() | self.item.dependencies()


@dataclass(frozen=True, slots=True)
class Record(Expression):
    fields: Mapping[str, Expression]
    def evaluate(self, env: EvaluationEnvironment) -> dict[str, Any]:
        return {key: self.fields[key].evaluate(env) for key in sorted(self.fields)}
    def dependencies(self) -> frozenset[str]:
        return frozenset().union(*(expr.dependencies() for expr in self.fields.values()))


@dataclass(frozen=True, slots=True)
class SumField(Expression):
    sequence: Expression
    field: str
    def evaluate(self, env: EvaluationEnvironment) -> Any:
        values = self.sequence.evaluate(env)
        return sum((item[self.field] for item in values), Decimal("0"))
    def dependencies(self) -> frozenset[str]:
        return self.sequence.dependencies()


class DerivationCycleError(ValueError):
    pass


def resolve_derivations(expressions: Mapping[str, Expression], env: EvaluationEnvironment) -> dict[str, Any]:
    names = set(expressions)
    dependencies = {name: set(expr.dependencies()) for name, expr in expressions.items()}
    unknown = sorted({dep for deps in dependencies.values() for dep in deps if dep not in names})
    if unknown:
        raise KeyError(f"unknown derived references: {', '.join(unknown)}")
    remaining = set(names)
    order: list[str] = []
    while remaining:
        ready = sorted(name for name in remaining if not (dependencies[name] & remaining))
        if not ready:
            raise DerivationCycleError("derived dependency cycle: " + ", ".join(sorted(remaining)))
        order.extend(ready)
        remaining.difference_update(ready)
    result: dict[str, Any] = {}
    for name in order:
        result[name] = expressions[name].evaluate(EvaluationEnvironment(env.pre_state, env.locals, result))
    return result
