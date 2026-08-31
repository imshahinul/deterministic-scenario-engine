"""Deterministic Phase 0.5 execution provenance."""
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping
from .values import normalize

@dataclass(frozen=True, slots=True)
class ProvenanceRecord:
    kind: str
    id: str
    execution_address: str | None = None
    step_id: str | None = None
    hook: str | None = None
    target: str | None = None
    outcome: str = "applied"
    details: Mapping[str, Any] = MappingProxyType({})

    def normalized(self):
        return normalize({"kind": self.kind, "id": self.id, "execution_address": self.execution_address,
            "step_id": self.step_id, "hook": self.hook, "target": self.target,
            "outcome": self.outcome, "details": self.details})

@dataclass(frozen=True, slots=True)
class ScenarioProvenance:
    records: tuple[ProvenanceRecord, ...] = ()
    def normalized(self): return [record.normalized() for record in self.records]
    def __iter__(self): return iter(self.records)
