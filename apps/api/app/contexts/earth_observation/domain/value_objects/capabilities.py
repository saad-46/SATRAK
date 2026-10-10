"""Provider capability descriptor.

Drives capability-based provider resolution (ADR-0007): the registry matches a request's
required capabilities against each provider's declared ``ProviderCapabilities`` rather than
switching on provider name.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.contexts.earth_observation.domain.enums import SensorType
from app.shared.domain.errors import ValueValidationError
from app.shared.domain.value_object import ValueObject


@dataclass(frozen=True)
class ProviderCapabilities(ValueObject):
    """What an imagery provider can do."""

    provider: str
    sensor_types: frozenset[SensorType]
    supports_tasking: bool = False
    min_gsd_m: float | None = None
    max_gsd_m: float | None = None

    def __post_init__(self) -> None:
        provider = self.provider.strip()
        if not provider:
            raise ValueValidationError("provider is required", field="provider")
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "sensor_types", frozenset(self.sensor_types))
        if not self.sensor_types:
            raise ValueValidationError("at least one sensor type is required", field="sensor_types")
        for name in ("min_gsd_m", "max_gsd_m"):
            value = getattr(self, name)
            if value is not None and (not math.isfinite(value) or value <= 0):
                raise ValueValidationError(f"{name} must be a finite, positive number", field=name)
        if (
            self.min_gsd_m is not None
            and self.max_gsd_m is not None
            and self.min_gsd_m > self.max_gsd_m
        ):
            raise ValueValidationError("min_gsd_m must be <= max_gsd_m", field="min_gsd_m")

    def supports(self, sensor_type: SensorType) -> bool:
        return sensor_type in self.sensor_types
