from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any, Mapping

from .address import ExecutionAddress
from .ids import LogicalID


@dataclass(frozen=True, slots=True)
class HistoryRecord:
    address: ExecutionAddress
    logical_timestamp: datetime
    pre_state_fingerprint: str
    state_patch: Mapping[str, Any]
    post_state_fingerprint: str
    emitted_artifacts: tuple[tuple[LogicalID, str], ...]
    transition_selected: str | None
    faults_applied: tuple[str, ...] | None = None


class ScenarioHistory:
    def __init__(self) -> None:
        self._records: list[HistoryRecord] = []

    @property
    def records(self) -> tuple[HistoryRecord, ...]:
        return tuple(self._records)

    def append_committed(self, record: HistoryRecord) -> None:
        frozen = MappingProxyType(dict(record.state_patch))
        self._records.append(HistoryRecord(
            record.address, record.logical_timestamp, record.pre_state_fingerprint,
            frozen, record.post_state_fingerprint, record.emitted_artifacts,
            record.transition_selected, record.faults_applied,
        ))
