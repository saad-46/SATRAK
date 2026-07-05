"""Physical measurement value objects: Distance, Area, Dimensions, Measurement.

Conversions normalize to SI base units (metres, square metres, cubic metres) so
comparisons and aggregation across sources are unambiguous — important when
satellite (metres) and cadastral (often acres/hectares) data meet.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from app.shared.domain.errors import ValueValidationError
from app.shared.domain.value_object import ValueObject


class DistanceUnit(StrEnum):
    METER = "m"
    KILOMETER = "km"
    FOOT = "ft"
    MILE = "mi"


_DISTANCE_TO_M: dict[DistanceUnit, Decimal] = {
    DistanceUnit.METER: Decimal("1"),
    DistanceUnit.KILOMETER: Decimal("1000"),
    DistanceUnit.FOOT: Decimal("0.3048"),
    DistanceUnit.MILE: Decimal("1609.344"),
}


class AreaUnit(StrEnum):
    SQUARE_METER = "sqm"
    SQUARE_KILOMETER = "sqkm"
    HECTARE = "ha"
    ACRE = "ac"


_AREA_TO_SQM: dict[AreaUnit, Decimal] = {
    AreaUnit.SQUARE_METER: Decimal("1"),
    AreaUnit.SQUARE_KILOMETER: Decimal("1000000"),
    AreaUnit.HECTARE: Decimal("10000"),
    AreaUnit.ACRE: Decimal("4046.8564224"),
}


@dataclass(frozen=True)
class Distance(ValueObject):
    value: Decimal
    unit: DistanceUnit = DistanceUnit.METER

    def __post_init__(self) -> None:
        value = _to_nonnegative_decimal(self.value, "distance")
        object.__setattr__(self, "value", value)

    @property
    def meters(self) -> Decimal:
        return self.value * _DISTANCE_TO_M[self.unit]


@dataclass(frozen=True)
class Area(ValueObject):
    value: Decimal
    unit: AreaUnit = AreaUnit.SQUARE_METER

    def __post_init__(self) -> None:
        value = _to_nonnegative_decimal(self.value, "area")
        object.__setattr__(self, "value", value)

    @property
    def square_meters(self) -> Decimal:
        return self.value * _AREA_TO_SQM[self.unit]


@dataclass(frozen=True)
class Dimensions(ValueObject):
    """3D dimensions in metres (length x width x height)."""

    length_m: Decimal
    width_m: Decimal
    height_m: Decimal

    def __post_init__(self) -> None:
        object.__setattr__(self, "length_m", _to_nonnegative_decimal(self.length_m, "length_m"))
        object.__setattr__(self, "width_m", _to_nonnegative_decimal(self.width_m, "width_m"))
        object.__setattr__(self, "height_m", _to_nonnegative_decimal(self.height_m, "height_m"))

    @property
    def volume_cubic_meters(self) -> Decimal:
        return self.length_m * self.width_m * self.height_m


@dataclass(frozen=True)
class Measurement(ValueObject):
    """A generic (value, unit) pair for domains without a dedicated VO."""

    value: Decimal
    unit: str

    def __post_init__(self) -> None:
        if not self.unit.strip():
            raise ValueValidationError("measurement unit is required", field="unit")
        try:
            object.__setattr__(self, "value", Decimal(self.value))
        except Exception as exc:
            raise ValueValidationError(f"invalid measurement value: {self.value!r}") from exc


def _to_nonnegative_decimal(raw: Decimal | int | str, field: str) -> Decimal:
    try:
        value = Decimal(raw)
    except Exception as exc:
        raise ValueValidationError(f"invalid {field}: {raw!r}", field=field) from exc
    if not value.is_finite() or value < 0:
        raise ValueValidationError(f"{field} must be a finite, non-negative number", field=field)
    return value
