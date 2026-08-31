from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping

from .values import canonical_bytes


class ExpressionEvaluationError(ValueError):
    pass


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


def _numeric(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, Decimal))


class Subtract(Binary):
    def evaluate(self, env: EvaluationEnvironment) -> Any:
        left, right = self.left.evaluate(env), self.right.evaluate(env)
        if not _numeric(left) or not _numeric(right):
            raise ExpressionEvaluationError("$sub operands must be integer or decimal")
        if isinstance(left, Decimal) or isinstance(right, Decimal):
            return Decimal(left) - Decimal(right)
        return left - right


class Divide(Binary):
    def evaluate(self, env: EvaluationEnvironment) -> Decimal:
        left, right = self.left.evaluate(env), self.right.evaluate(env)
        if not _numeric(left) or not _numeric(right):
            raise ExpressionEvaluationError("$div operands must be integer or decimal")
        if right == 0:
            raise ExpressionEvaluationError("$div division by zero")
        return Decimal(left) / Decimal(right)


class Equal(Binary):
    def evaluate(self, env: EvaluationEnvironment) -> bool:
        return canonical_bytes(self.left.evaluate(env)) == canonical_bytes(self.right.evaluate(env))


class NotEqual(Equal):
    def evaluate(self, env: EvaluationEnvironment) -> bool:
        return not super().evaluate(env)


def _ordered(left: Any, right: Any) -> tuple[Any, Any]:
    from datetime import datetime
    if _numeric(left) and _numeric(right):
        return (Decimal(left), Decimal(right))
    if isinstance(left, str) and isinstance(right, str):
        return left, right
    if isinstance(left, datetime) and isinstance(right, datetime):
        if left.tzinfo is None or right.tzinfo is None:
            raise ExpressionEvaluationError("ordering datetimes must be timezone-aware")
        return left, right
    raise ExpressionEvaluationError("ordering operands have incompatible semantic types")


class LessThan(Binary):
    def evaluate(self, env: EvaluationEnvironment) -> bool:
        return _ordered(self.left.evaluate(env), self.right.evaluate(env))[0] < _ordered(self.left.evaluate(env), self.right.evaluate(env))[1]


class LessThanOrEqual(Binary):
    def evaluate(self, env: EvaluationEnvironment) -> bool:
        left, right = _ordered(self.left.evaluate(env), self.right.evaluate(env)); return left <= right


class GreaterThan(Binary):
    def evaluate(self, env: EvaluationEnvironment) -> bool:
        left, right = _ordered(self.left.evaluate(env), self.right.evaluate(env)); return left > right


class GreaterThanOrEqual(Binary):
    def evaluate(self, env: EvaluationEnvironment) -> bool:
        left, right = _ordered(self.left.evaluate(env), self.right.evaluate(env)); return left >= right


@dataclass(frozen=True, slots=True)
class BooleanMany(Expression):
    operands: tuple[Expression, ...]
    use_and: bool
    def evaluate(self, env: EvaluationEnvironment) -> bool:
        result = True if self.use_and else False
        for operand in self.operands:
            value = operand.evaluate(env)
            if type(value) is not bool:
                raise ExpressionEvaluationError("boolean operator operands must be boolean")
            result = result and value if self.use_and else result or value
        return result
    def dependencies(self) -> frozenset[str]:
        return frozenset().union(*(operand.dependencies() for operand in self.operands))


@dataclass(frozen=True, slots=True)
class BooleanNot(Expression):
    operand: Expression
    def evaluate(self, env: EvaluationEnvironment) -> bool:
        value = self.operand.evaluate(env)
        if type(value) is not bool:
            raise ExpressionEvaluationError("$not operand must be boolean")
        return not value
    def dependencies(self) -> frozenset[str]:
        return self.operand.dependencies()


@dataclass(frozen=True, slots=True)
class Length(Expression):
    operand: Expression
    def evaluate(self, env: EvaluationEnvironment) -> int:
        value = self.operand.evaluate(env)
        if not isinstance(value, (str, list, tuple, Mapping)):
            raise ExpressionEvaluationError("$len operand must be string, list, or map")
        return len(value)
    def dependencies(self) -> frozenset[str]:
        return self.operand.dependencies()


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
