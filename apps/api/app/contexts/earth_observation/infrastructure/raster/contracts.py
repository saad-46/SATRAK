"""GDAL/rasterio seam contracts (Epic 3 Story 12).

COG writing and reprojection require GDAL; these Protocols are the exact seam a
GDAL/rasterio adapter implements when that dependency is introduced (spec §9). Nothing
above this module may import a raster library — the engine's pure operations plus these
contracts are the whole surface.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol, runtime_checkable

from app.contexts.earth_observation.domain.value_objects.crs import CrsRef
from app.contexts.earth_observation.infrastructure.raster.dataset import RasterDataset


class RasterCompression(StrEnum):
    """Creation-time compression for analysis tiers (lossless only; spec §7.3)."""

    DEFLATE = "deflate"
    ZSTD = "zstd"
    NONE = "none"


@runtime_checkable
class CogWriter(Protocol):
    """Writes a dataset as a validated Cloud-Optimized GeoTIFF (internal tiling + overviews)."""

    async def write_cog(
        self,
        *,
        dataset: RasterDataset,
        target_uri: str,
        compression: RasterCompression = RasterCompression.DEFLATE,
    ) -> None: ...


@runtime_checkable
class Reprojector(Protocol):
    """Warps a stored raster into a target CRS (national projected CRS for analysis)."""

    async def reproject(self, *, source_uri: str, target_uri: str, target_crs: CrsRef) -> None: ...
