from __future__ import annotations

from dataclasses import dataclass, replace
import json

from .diagnostics import semantic_address


@dataclass(frozen=True, slots=True)
class ExecutionAddress:
    scenario_id: str
    run_index: int = 0
    subflow_invocations: tuple[int, ...] = ()
    repetition_indexes: tuple[int, ...] = ()
    step_id: str | None = None
    semantic_path: tuple[str, ...] = ()
    actor_id: str | None = None

    def for_step(self, step_id: str) -> ExecutionAddress:
        return replace(self, step_id=step_id, semantic_path=())

    def child(self, *path: str) -> ExecutionAddress:
        return replace(self, semantic_path=self.semantic_path + tuple(path))

    def with_subflow_invocation(self, index: int) -> ExecutionAddress:
        return replace(self, subflow_invocations=self.subflow_invocations + (index,))

    def with_repetition(self, index: int) -> ExecutionAddress:
        return replace(self, repetition_indexes=self.repetition_indexes + (index,))

    def canonical(self) -> str:
        value = {
            "path": list(self.semantic_path),
            "repetitions": list(self.repetition_indexes),
            "run": self.run_index,
            "scenario": self.scenario_id,
            "step": self.step_id,
            "subflows": list(self.subflow_invocations),
        }
        # Engine 1 bytes remain frozen: actor identity is present only for the
        # explicitly internal DSL 2 execution path.
        if self.actor_id is not None:
            value["actor"] = self.actor_id
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    def semantic(self) -> str | None:
        """Return the canonical semantic identity when this is actor-scoped."""
        if self.actor_id is None:
            return semantic_address(("step", self.step_id)) if self.step_id is not None else None
        components = (("actor", self.actor_id),)
        if self.step_id is not None:
            components += (("step", self.step_id),)
        return semantic_address(*components, activate_actor=True)
