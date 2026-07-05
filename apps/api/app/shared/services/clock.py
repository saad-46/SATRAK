"""Clock service — injectable time.

Depending on a :class:`Clock` instead of calling ``datetime.now()`` directly makes
time an explicit dependency, so time-sensitive logic is deterministically testable
via :class:`FixedClock`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    """Real wall-clock time (timezone-aware UTC)."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class FixedClock:
    """A clock frozen at a fixed instant; advanceable in tests."""

    def __init__(self, fixed: datetime) -> None:
        self._now = fixed

    def now(self) -> datetime:
        return self._now

    def set(self, moment: datetime) -> None:
        self._now = moment
