from __future__ import annotations

from dataclasses import dataclass
import hashlib
import random

from .address import ExecutionAddress


RNG_VERSION = "scenario-engine-addressed-v1"


class DeterministicRNG:
    def __init__(self, root_seed: str | int, address: ExecutionAddress):
        self._root_seed = str(root_seed)
        self._address = address

    def derivation_material(self, generator_type: str) -> bytes:
        parts = (RNG_VERSION, self._root_seed, self._address.canonical(), generator_type)
        return "\x1f".join(parts).encode("utf-8")

    def inclusive_int(self, minimum: int, maximum: int) -> int:
        if minimum > maximum:
            raise ValueError("minimum must not exceed maximum")
        digest = hashlib.sha256(self.derivation_material("inclusive-int")).digest()
        local = random.Random(int.from_bytes(digest, "big"))
        return local.randint(minimum, maximum)


@dataclass(frozen=True, slots=True)
class IntegerRange:
    minimum: int
    maximum: int

    def generate(self, context: object) -> int:
        return context.rng().inclusive_int(self.minimum, self.maximum)  # type: ignore[attr-defined]
