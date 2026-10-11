"""Spatial resolution (ground sample distance)."""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.shared.domain.errors import ValueValidationError
from app.shared.domain.value_object import ValueObject

_SUB_METER_THRESHOLD_M = 1.0


@dataclass(frozen=True)
class Resolution(ValueObject):
    """Ground sample distance (GSD) — the ground length of one pixel, in metres."""

    gsd_m: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.gsd_m) or self.gsd_m <= 0:
            raise ValueValidationError("gsd_m must be a finite, positive number", field="gsd_m")

    @property
    def gsd_cm(self) -> float:
        return self.gsd_m * 100.0

    @property
    def is_sub_meter(self) -> bool:
        return self.gsd_m < _SUB_METER_THRESHOLD_M

    def is_finer_than(self, other: Resolution) -> bool:
        """A smaller GSD means finer detail."""
        return self.gsd_m < other.gsd_m
