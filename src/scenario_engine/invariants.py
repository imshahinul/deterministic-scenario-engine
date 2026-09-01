"""Candidate-post-state invariant definitions and evaluation."""
from types import MappingProxyType
from .errors import ScenarioEngineError
from .expressions import EvaluationEnvironment

class InvariantError(ScenarioEngineError, ValueError): pass
class InvariantDefinitionError(InvariantError): pass
class InvariantViolation(InvariantError):
    def __init__(self, invariant_id, step_id, execution_address, reason=None):
        self.invariant_id, self.step_id, self.execution_address = invariant_id, step_id, execution_address
        super().__init__(reason or f"invariant {invariant_id} violated at step {step_id}")

def evaluate_invariants(invariants, candidate_state, step_id, address, record):
    env = EvaluationEnvironment(candidate_state, MappingProxyType({}), MappingProxyType({}))
    for invariant_id, expression in invariants:
        result = expression.evaluate(env)
        if type(result) is not bool:
            raise InvariantDefinitionError(f"invariant {invariant_id}: check must return boolean")
        record(invariant_id, "passed" if result else "violation", address, step_id)
        if not result:
            raise InvariantViolation(invariant_id, step_id, address.canonical())
