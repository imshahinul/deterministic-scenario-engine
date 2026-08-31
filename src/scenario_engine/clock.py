from __future__ import annotations

from datetime import datetime, timedelta, timezone


class LogicalClock:
    def __init__(self, reference: datetime):
        if reference.tzinfo is None or reference.utcoffset() is None:
            raise ValueError("logical clock reference must be timezone-aware")
        self._current = reference.astimezone(timezone.utc)

    @property
    def current(self) -> datetime:
        return self._current

    def prospective(self, advance: timedelta) -> datetime:
        return self._current + advance

    def commit(self, timestamp: datetime) -> None:
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("committed timestamp must be timezone-aware")
        self._current = timestamp.astimezone(timezone.utc)
