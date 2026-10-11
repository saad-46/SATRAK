"""Raster operations: band selection, clipping, normalization, validation (Story 12).

All operations are dataset-in/dataset-out (or report-out), provider-independent, and
process row chunks — never whole scenes — per the platform's streaming requirement.
Reprojection and COG writing need GDAL and live behind the contracts in
``contracts.py``.
"""

from __future__ import annotations

import math
from array import array
from collections.abc import Sequence
from dataclasses import dataclass

from app.contexts.earth_observation.infrastructure.raster.dataset import (
    InMemoryRaster,
    RasterDataset,
)
from app.contexts.earth_observation.infrastructure.raster.grid import (
    RasterGrid,
    iter_windows,
)
from app.contexts.earth_observation.infrastructure.raster.stats import (
    BandStatistics,
    compute_statistics,
)
from app.shared.domain.errors import ValueValidationError
from app.shared.value_objects.geo import BoundingBox


def select_bands(dataset: RasterDataset, *, bands: Sequence[int]) -> InMemoryRaster:
    """A new raster holding only the requested bands (chunked copy)."""
    if not bands:
        raise ValueValidationError("at least one band must be selected", field="bands")
    grid = dataset.grid
    out_grid = RasterGrid(
        width=grid.width,
        height=grid.height,
        band_count=len(bands),
        crs=grid.crs,
        origin_x=grid.origin_x,
        origin_y=grid.origin_y,
        pixel_size=grid.pixel_size,
    )
    buffers: list[array[float]] = [array("f") for _ in bands]
    for window in iter_windows(grid, tile_width=grid.width, tile_height=256):
        block = dataset.read(window=window, bands=tuple(bands))
        for position, _ in enumerate(bands):
            buffers[position].extend(block.data[position])
    return InMemoryRaster(grid=out_grid, bands=buffers)


def clip(dataset: RasterDataset, *, bbox: BoundingBox) -> InMemoryRaster:
    """The sub-raster covering ``bbox`` (grid-CRS coordinates), reading only that window."""
    window = dataset.grid.window_for_bbox(bbox)
    block = dataset.read(window=window)
    out_grid = dataset.grid.grid_for_window(window)
    return InMemoryRaster(grid=out_grid, bands=block.data)


def minmax_normalize(
    dataset: RasterDataset, *, statistics: Sequence[BandStatistics] | None = None
) -> InMemoryRaster:
    """Scale every band to ``[0, 1]`` using (min, max); constant bands become zeros."""
    grid = dataset.grid
    stats = (
        list(statistics)
        if statistics is not None
        else [compute_statistics(dataset, band=b) for b in range(grid.band_count)]
    )
    if len(stats) != grid.band_count:
        raise ValueValidationError("one statistics entry per band required", field="statistics")
    buffers: list[array[float]] = [array("f") for _ in range(grid.band_count)]
    for window in iter_windows(grid, tile_width=grid.width, tile_height=256):
        block = dataset.read(window=window)
        for band in range(grid.band_count):
            low, high = stats[band].minimum, stats[band].maximum
            span = high - low
            if span <= 0:
                buffers[band].extend([0.0] * block.window.pixel_count)
            else:
                buffers[band].extend((value - low) / span for value in block.data[band])
    return InMemoryRaster(grid=grid, bands=buffers)


@dataclass(frozen=True)
class RasterIssue:
    """One raster-validation finding."""

    code: str
    message: str


def validate_dataset(dataset: RasterDataset, *, chunk_height: int = 256) -> tuple[RasterIssue, ...]:
    """Structural validation: every band readable end-to-end and free of non-finite values."""
    issues: list[RasterIssue] = []
    grid = dataset.grid
    for band in range(grid.band_count):
        non_finite = 0
        try:
            for window in iter_windows(grid, tile_width=grid.width, tile_height=chunk_height):
                block = dataset.read(window=window, bands=(band,))
                non_finite += sum(1 for value in block.data[0] if not math.isfinite(value))
        except ValueValidationError as exc:
            issues.append(RasterIssue(code="unreadable_band", message=f"band {band}: {exc}"))
            continue
        if non_finite:
            issues.append(
                RasterIssue(
                    code="non_finite_pixels",
                    message=f"band {band} contains {non_finite} non-finite pixels",
                )
            )
    return tuple(issues)
