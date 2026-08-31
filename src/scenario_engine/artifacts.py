from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .address import ExecutionAddress
from .ids import LogicalID


@dataclass(frozen=True, slots=True)
class GeneratedArtifact:
    artifact_type: str
    name: str
    value: Any
    logical_id: LogicalID
    address: ExecutionAddress
