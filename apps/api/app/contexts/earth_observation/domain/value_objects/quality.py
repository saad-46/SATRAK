"""Scene quality value objects: CloudCoverPercentage and QualityScore."""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.shared.domain.errors import ValueValidationError
from app.shared.domain.value_object import ValueObject

_DEFAULT_CLEAR_THRESHOLD = 10.0


@dataclass(frozen=True)
class CloudCoverPercentage(ValueObject):
    """Cloud cover as a percentage in ``[0, 100]`` (optical scenes only)."""

    value: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.value) or not 0.0 <= self.value <= 100.0:
            raise ValueValidationError("cloud cover must be a number in [0, 100]", field="value")

    @property
    def fraction(self) -> float:
        return self.value / 100.0

    def is_clear(self, *, threshold: float = _DEFAULT_CLEAR_THRESHOLD) -> bool:
        return self.value <= threshold


@dataclass(frozen=True)
class QualityScore(ValueObject):
    """A composite quality score in ``[0, 1]`` (higher is better)."""

    value: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.value) or not 0.0 <= self.value <= 1.0:
            raise ValueValidationError("quality score must be a number in [0, 1]", field="value")
