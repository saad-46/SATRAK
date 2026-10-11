"""Raster processing port.

Domain-facing contract for raster operations; the concrete GDAL/rasterio adapter (built on
``packages/py-raster``) lives in ``infrastructure/raster`` (Story 12). No implementation
here.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.contexts.earth_observation.domain.value_objects.crs import CrsRef
from app.shared.value_objects.geo import BoundingBox


@runtime_checkable
class RasterProcessor(Protocol):
    """Stateless raster operations keyed by storage URIs (references, not pixels)."""

    async def to_cog(self, *, source_uri: str, target_uri: str) -> None: ...

    async def reproject(self, *, source_uri: str, target_uri: str, target_crs: CrsRef) -> None: ...

    async def clip(self, *, source_uri: str, target_uri: str, area: BoundingBox) -> None: ...
