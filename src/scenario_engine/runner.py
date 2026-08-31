from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from types import MappingProxyType
from typing import Any, Callable, Mapping, Protocol

from .address import ExecutionAddress
from .artifacts import GeneratedArtifact
from .clock import LogicalClock
from .context import GenerationContext
from .expressions import EvaluationEnvironment, Expression, resolve_derivations
from .history import HistoryRecord, ScenarioHistory
from .ids import DeterministicIDProvider
from .state import ScenarioState
from .values import fingerprint


class Generator(Protocol):
    def generate(self, context: GenerationContext) -> Any: ...


EmissionBuilder = Callable[[GenerationContext, Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]], tuple[GeneratedArtifact, ...]]
TransitionResolver = Callable[[Mapping[str, Any]], str | None]
Validator = Callable[[Mapping[str, Any]], None]
HistoryBuilder = Callable[..., HistoryRecord]


@dataclass(frozen=True, slots=True)
class StepSpec:
    step_id: str
    generators: Mapping[str, Generator]
    derivations: Mapping[str, Expression]
    state_patch: Mapping[str, Expression]
    advance: timedelta = timedelta(0)
    validate: Validator = lambda state: None
    emit: EmissionBuilder = lambda context, state, locals_, derived: ()
    transition: TransitionResolver = lambda state: None
    history_builder: HistoryBuilder = HistoryRecord


@dataclass(frozen=True, slots=True)
class CandidateStep:
    post_state: Mapping[str, Any]
    artifacts: tuple[GeneratedArtifact, ...]
    timestamp: Any
    transition: str | None
    history_record: HistoryRecord


class ScenarioRunner:
    def __init__(self, root_seed: str | int, address: ExecutionAddress,
                 state: ScenarioState, clock: LogicalClock):
        self.root_seed = root_seed
        self.address = address
        self.state = state
        self.clock = clock
        self.history = ScenarioHistory()
        self.artifacts: list[GeneratedArtifact] = []
        self.next_step: str | None = None
        self._ids = DeterministicIDProvider(root_seed)

    def run_step(self, spec: StepSpec) -> CandidateStep:
        step_address = self.address.for_step(spec.step_id)
        context = GenerationContext(self.root_seed, step_address, self.clock, self._ids)
        pre_state = self.state.snapshot()
        pre_fingerprint = self.state.fingerprint()

        locals_: dict[str, Any] = {}
        for name in sorted(spec.generators):
            field_context = context.at(step_address.child("generate", name))
            locals_[name] = spec.generators[name].generate(field_context)

        base_env = EvaluationEnvironment(pre_state, MappingProxyType(locals_), MappingProxyType({}))
        derived = resolve_derivations(spec.derivations, base_env)
        resolved_env = EvaluationEnvironment(pre_state, MappingProxyType(locals_), MappingProxyType(derived))
        patch = {name: spec.state_patch[name].evaluate(resolved_env) for name in sorted(spec.state_patch)}
        post_state = self.state.candidate(patch)
        safe_post_state = MappingProxyType(post_state)
        spec.validate(safe_post_state)
        timestamp = self.clock.prospective(spec.advance)
        artifacts = tuple(spec.emit(context, safe_post_state, MappingProxyType(locals_), MappingProxyType(derived)))
        transition = spec.transition(safe_post_state)
        record = spec.history_builder(
            address=step_address,
            logical_timestamp=timestamp,
            pre_state_fingerprint=pre_fingerprint,
            state_patch=MappingProxyType(patch),
            post_state_fingerprint=fingerprint(post_state),
            emitted_artifacts=tuple((item.logical_id, item.artifact_type) for item in artifacts),
            transition_selected=transition,
            faults_applied=None,
        )
        candidate = CandidateStep(safe_post_state, artifacts, timestamp, transition, record)

        self.state.commit(post_state)
        self.history.append_committed(record)
        self.artifacts.extend(artifacts)
        self.clock.commit(timestamp)
        self.next_step = transition
        return candidate
