from __future__ import annotations

from dataclasses import dataclass
import hashlib
import uuid

from .address import ExecutionAddress


ID_VERSION = "scenario-engine-id-v1"


@dataclass(frozen=True, slots=True)
class LogicalID:
    value: str

    def __post_init__(self) -> None:
        canonical = str(uuid.UUID(self.value))
        object.__setattr__(self, "value", canonical)

    def __str__(self) -> str:
        return self.value


class DeterministicIDProvider:
    def __init__(self, root_seed: str | int):
        self._root_seed = str(root_seed)

    def derivation_material(self, address: ExecutionAddress, slot: str) -> bytes:
        return "\x1f".join((ID_VERSION, self._root_seed, address.canonical(), slot)).encode()

    def derive(self, address: ExecutionAddress, slot: str) -> LogicalID:
        raw = bytearray(hashlib.sha256(self.derivation_material(address, slot)).digest()[:16])
        raw[6] = (raw[6] & 0x0F) | 0x50
        raw[8] = (raw[8] & 0x3F) | 0x80
        return LogicalID(str(uuid.UUID(bytes=bytes(raw))))
