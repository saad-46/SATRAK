"""Earth Observation aggregate roots (Epic 3 Stories 3-4)."""

from __future__ import annotations

from app.contexts.earth_observation.domain.aggregates.aoi import AreaOfInterest
from app.contexts.earth_observation.domain.aggregates.scene import Scene

__all__ = ["AreaOfInterest", "Scene"]
