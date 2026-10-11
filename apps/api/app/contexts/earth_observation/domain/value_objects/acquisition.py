"""Acquisition metadata — the capture-time facts about a scene."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from app.contexts.earth_observation.domain.enums import SensorType
from app.contexts.earth_observation.domain.value_objects.quality import CloudCoverPercentage
from app.shared.domain.errors import ValueValidationError
from app.shared.domain.value_object import ValueObject


@dataclass(frozen=True)
class AcquisitionMetadata(ValueObject):
    """When and how a scene was captured.

    Cloud cover and sun geometry are optical-only; for ``SensorType.SAR`` they must be
    absent (a SAR scene has no cloud fraction or sun angle) — a capability-based invariant
    that keeps consumers from branching on provider name (ADR-0007, spec §5.5).
    """

    acquired_at: datetime
    sensor_type: SensorType
    cloud_cover: CloudCoverPercentage | None = None
    sun_azimuth_deg: float | None = None
    sun_elevation_deg: float | None = None
    off_nadir_deg: float | None = None

    def __post_init__(self) -> None:
        if self.acquired_at.tzinfo is None:
            raise ValueValidationError("acquired_at must be timezone-aware", field="acquired_at")
        self._check_angle(self.sun_azimuth_deg, "sun_azimuth_deg", 0.0, 360.0)
        self._check_angle(self.sun_elevation_deg, "sun_elevation_deg", -90.0, 90.0)
        self._check_angle(self.off_nadir_deg, "off_nadir_deg", 0.0, 90.0)
        if self.sensor_type is SensorType.SAR:
            if self.cloud_cover is not None:
                raise ValueValidationError(
                    "SAR scenes do not carry cloud cover", field="cloud_cover"
                )
            if self.sun_azimuth_deg is not None or self.sun_elevation_deg is not None:
                raise ValueValidationError(
                    "SAR scenes do not carry sun geometry", field="sensor_type"
                )

    @staticmethod
    def _check_angle(value: float | None, field: str, low: float, high: float) -> None:
        if value is None:
            return
        if not math.isfinite(value) or not low <= value <= high:
            raise ValueValidationError(f"{field} must be in [{low}, {high}]", field=field)
