"""Aspect-preserving nearest-neighbour downsampling (Epic 3 Story 15).

Reads one source row window at a time, so downsampling a scene never materialises more
than a single raster row. Never upscales — a source smaller than the target is returned
at native size.
"""

from __future__ import annotations

from array import array

from app.contexts.earth_observation.infrastructure.raster.dataset import RasterDataset
from app.contexts.earth_observation.infrastructure.raster.grid import Window
from app.shared.domain.errors import ValueValidationError


def downsample_to_fit(
    dataset: RasterDataset, *, max_dimension: int
) -> tuple[int, int, tuple[array[float], ...]]:
    """``(width, height, bands)`` scaled to fit ``max_dimension``, aspect ratio preserved."""
    if max_dimension < 1:
        raise ValueValidationError("max_dimension must be >= 1", field="max_dimension")
    grid = dataset.grid
    scale = min(1.0, max_dimension / max(grid.width, grid.height))
    out_width = max(1, round(grid.width * scale))
    out_height = max(1, round(grid.height * scale))

    source_cols = [
        min(grid.width - 1, int(col * grid.width / out_width)) for col in range(out_width)
    ]
    buffers: tuple[array[float], ...] = tuple(array("f") for _ in range(grid.band_count))
    for out_row in range(out_height):
        source_row = min(grid.height - 1, int(out_row * grid.height / out_height))
        block = dataset.read(
            window=Window(col_off=0, row_off=source_row, width=grid.width, height=1)
        )
        for band in range(grid.band_count):
            row_data = block.data[band]
            buffers[band].extend(row_data[col] for col in source_cols)
    return out_width, out_height, buffers
