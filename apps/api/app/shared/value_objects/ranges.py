"""Temporal range value objects: DateRange and TimeRange."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from app.shared.domain.errors import ValueValidationError
from app.shared.domain.value_object import ValueObject


@dataclass(frozen=True)
class DateRange(ValueObject):
    """An inclusive calendar-date range (``start`` <= ``end``)."""

    start: date
    end: date

    def __post_init__(self) -> None:
        if self.start > self.end:
            raise ValueValidationError("DateRange start must be <= end")

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def contains(self, day: date) -> bool:
        return self.start <= day <= self.end

    def overlaps(self, other: DateRange) -> bool:
        return self.start <= other.end and other.start <= self.end


@dataclass(frozen=True)
class TimeRange(ValueObject):
    """An instant range (``start`` <= ``end``), timezone-aware datetimes expected."""

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.start > self.end:
            raise ValueValidationError("TimeRange start must be <= end")

    @property
    def duration_seconds(self) -> float:
        return (self.end - self.start).total_seconds()

    def contains(self, moment: datetime) -> bool:
        return self.start <= moment <= self.end

    def overlaps(self, other: TimeRange) -> bool:
        return self.start <= other.end and other.start <= self.end
