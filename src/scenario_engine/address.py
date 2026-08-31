from __future__ import annotations

from dataclasses import dataclass, replace
import json


@dataclass(frozen=True, slots=True)
class ExecutionAddress:
    scenario_id: str
    run_index: int = 0
    subflow_invocations: tuple[int, ...] = ()
    repetition_indexes: tuple[int, ...] = ()
    step_id: str | None = None
    semantic_path: tuple[str, ...] = ()

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
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
