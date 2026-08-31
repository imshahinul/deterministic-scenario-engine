from __future__ import annotations

from dataclasses import dataclass

from .address import ExecutionAddress
from .clock import LogicalClock
from .ids import DeterministicIDProvider, LogicalID
from .rng import DeterministicRNG


@dataclass(frozen=True, slots=True)
class GenerationContext:
    root_seed: str | int
    address: ExecutionAddress
    clock: LogicalClock
    ids: DeterministicIDProvider

    def rng(self) -> DeterministicRNG:
        return DeterministicRNG(self.root_seed, self.address)

    def logical_id(self, slot: str) -> LogicalID:
        return self.ids.derive(self.address, slot)

    def at(self, address: ExecutionAddress) -> GenerationContext:
        return GenerationContext(self.root_seed, address, self.clock, self.ids)
