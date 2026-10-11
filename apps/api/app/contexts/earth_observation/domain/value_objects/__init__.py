"""Earth Observation value objects — immutable, self-validating (Epic 3 Story 2).

Reuses the shared geospatial VOs (``Coordinates``/``GeoPoint``/``BoundingBox``) and
``TimeRange`` from the shared kernel; adds EO-specific values here.
"""

from __future__ import annotations

from app.contexts.earth_observation.domain.value_objects.acquisition import AcquisitionMetadata
from app.contexts.earth_observation.domain.value_objects.band import Band, BandSet
from app.contexts.earth_observation.domain.value_objects.capabilities import ProviderCapabilities
from app.contexts.earth_observation.domain.value_objects.crs import WEB_MERCATOR_SRID, CrsRef
from app.contexts.earth_observation.domain.value_objects.quality import (
    CloudCoverPercentage,
    QualityScore,
)
from app.contexts.earth_observation.domain.value_objects.resolution import Resolution
from app.contexts.earth_observation.domain.value_objects.scene_id import ProviderSceneId
from app.contexts.earth_observation.domain.value_objects.tile import (
    WEB_MERCATOR_QUAD,
    TileCoord,
    TileMatrixSetRef,
)

__all__ = [
    "WEB_MERCATOR_QUAD",
    "WEB_MERCATOR_SRID",
    "AcquisitionMetadata",
    "Band",
    "BandSet",
    "CloudCoverPercentage",
    "CrsRef",
    "ProviderCapabilities",
    "ProviderSceneId",
    "QualityScore",
    "Resolution",
    "TileCoord",
    "TileMatrixSetRef",
]
