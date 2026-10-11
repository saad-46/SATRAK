"""Placeholder interfaces for the shared raster-processing package.

Epic 3 Story 1 scaffold — **no implementation**. The concrete GDAL/rasterio adapter and
the full operation set (crop, clip, merge, warp/reproject, orthorectify, normalize,
cloud-mask, histogram/stats, pyramids, COG, compression) land in a later Earth Observation
story; see ``docs/epic-3-earth-observation-platform-spec.md`` §9.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class RasterEngine(Protocol):
    """Stateless, provider-agnostic raster operations.

    Placeholder interface: the method contract is finalized in a later story. The single
    signature below is indicative only.
    """

    def to_cog(self, source_uri: str, target_uri: str) -> None:
        """Produce a validated Cloud-Optimized GeoTIFF from a source raster."""
        ...
