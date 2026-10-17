"""Raster processing engine (Epic 3 Story 12).

Provider-independent, window-addressed raster operations built on `packages/py-raster`'s
design: chunked statistics/histograms, band selection, clipping, normalization, and
structural validation over the ``RasterDataset`` contract. GDAL/rasterio enter only
through the ``CogWriter``/``Reprojector`` seams in ``contracts.py``.
"""

from __future__ import annotations

from app.contexts.earth_observation.infrastructure.raster.contracts import (
    CogWriter,
    RasterCompression,
    Reprojector,
)
from app.contexts.earth_observation.infrastructure.raster.dataset import (
    InMemoryRaster,
    RasterBlock,
    RasterDataset,
)
from app.contexts.earth_observation.infrastructure.raster.grid import (
    RasterGrid,
    Window,
    iter_windows,
)
from app.contexts.earth_observation.infrastructure.raster.ops import (
    RasterIssue,
    clip,
    minmax_normalize,
    select_bands,
    validate_dataset,
)
from app.contexts.earth_observation.infrastructure.raster.stats import (
    BandStatistics,
    Histogram,
    compute_histogram,
    compute_statistics,
)

__all__ = [
    "BandStatistics",
    "CogWriter",
    "Histogram",
    "InMemoryRaster",
    "RasterBlock",
    "RasterCompression",
    "RasterDataset",
    "RasterGrid",
    "RasterIssue",
    "Reprojector",
    "Window",
    "clip",
    "compute_histogram",
    "compute_statistics",
    "iter_windows",
    "minmax_normalize",
    "select_bands",
    "validate_dataset",
]
