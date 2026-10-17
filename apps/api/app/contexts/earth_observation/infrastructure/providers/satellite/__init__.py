"""Spaceborne provider family (Epic 3 Stories 6-7).

One module per provider; adding a provider touches only this tree (ADR-0007).
"""

from __future__ import annotations

from app.contexts.earth_observation.infrastructure.providers.satellite.sentinel2 import (
    SENTINEL2_BANDS,
    Sentinel2Provider,
)

__all__ = ["SENTINEL2_BANDS", "Sentinel2Provider"]
