"""Domain ports (Protocols) for the Earth Observation context (Epic 3 Story 5).

Contracts only — the application layer depends on these; concrete adapters live in
``infrastructure`` in later stories. The storage port reuses the shared-kernel
``StorageProvider`` (DRY).
"""

from __future__ import annotations

from app.contexts.earth_observation.domain.ports.imagery_provider import (
    EarthObservationProvider,
    SceneCandidate,
)
from app.contexts.earth_observation.domain.ports.metadata_extractor import (
    ExtractedMetadata,
    MetadataExtractor,
)
from app.contexts.earth_observation.domain.ports.raster_processor import RasterProcessor
from app.contexts.earth_observation.domain.ports.repositories import (
    AoiRepository,
    SceneRepository,
)
from app.contexts.earth_observation.domain.ports.storage import ImageStoragePort
from app.contexts.earth_observation.domain.ports.tile_generator import TileGenerator
from app.contexts.earth_observation.domain.ports.timeline_provider import TimelineProvider

__all__ = [
    "AoiRepository",
    "EarthObservationProvider",
    "ExtractedMetadata",
    "ImageStoragePort",
    "MetadataExtractor",
    "RasterProcessor",
    "SceneCandidate",
    "SceneRepository",
    "TileGenerator",
    "TimelineProvider",
]
