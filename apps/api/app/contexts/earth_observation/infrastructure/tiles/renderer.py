"""Windowed XYZ tile rendering (Epic 3 Story 14).

Renders one tile by nearest-neighbour sampling of a windowed ``RasterDataset``: per
output row the Mercator latitude is computed exactly, mapped to a source row, and that
single row window is read (and reused while consecutive output rows hit the same source
row) — so memory stays bounded by one raster row regardless of scene size. Pixels
outside the dataset extent become ``nodata``. Output is deterministic: same dataset +
coordinate -> byte-identical pixels and checksum.

The dataset is expected in the WGS84 interchange surface; reprojection into it is the
``Reprojector`` seam's job (future COG workflows read the same windows via rasterio).
"""

from __future__ import annotations

import hashlib
from array import array
from collections.abc import Sequence
from dataclasses import dataclass

from app.contexts.earth_observation.domain.value_objects.tile import TileCoord
from app.contexts.earth_observation.infrastructure.raster.dataset import RasterDataset
from app.contexts.earth_observation.infrastructure.raster.encoding import pack_float32_le
from app.contexts.earth_observation.infrastructure.raster.grid import Window
from app.contexts.earth_observation.infrastructure.tiles.tile_matrix import (
    tile_bounds_wgs84,
    tile_row_latitude,
)
from app.shared.domain.errors import ValueValidationError


@dataclass(frozen=True)
class GeneratedTile:
    """One rendered tile: pixel buffers plus its deterministic content fingerprint."""

    coord: TileCoord
    tile_size: int
    band_indexes: tuple[int, ...]
    data: tuple[array[float], ...]

    @property
    def checksum_sha256(self) -> str:
        return hashlib.sha256(pack_float32_le(self.data)).hexdigest()


def render_tile(
    dataset: RasterDataset,
    coord: TileCoord,
    *,
    tile_size: int = 256,
    bands: Sequence[int] | None = None,
    nodata: float = 0.0,
) -> GeneratedTile:
    """Nearest-neighbour render of ``coord`` from the dataset (row-cached, windowed)."""
    if tile_size < 1:
        raise ValueValidationError("tile_size must be >= 1", field="tile_size")
    grid = dataset.grid
    band_indexes = tuple(bands) if bands is not None else tuple(range(grid.band_count))
    bounds = tile_bounds_wgs84(coord)

    # Source column per output column (or -1 for nodata) — computed once per tile.
    lon_step = (bounds.max_longitude - bounds.min_longitude) / tile_size
    source_cols: list[int] = []
    for out_col in range(tile_size):
        lon = bounds.min_longitude + (out_col + 0.5) * lon_step
        col = int((lon - grid.origin_x) / grid.pixel_size)
        source_cols.append(col if 0 <= col < grid.width else -1)

    buffers: tuple[array[float], ...] = tuple(array("f") for _ in band_indexes)
    nodata_row = [nodata] * tile_size
    cached_row = -1
    cached: tuple[array[float], ...] | None = None
    for out_row in range(tile_size):
        # Exact Mercator latitude of this output row's centre.
        latitude = tile_row_latitude(zoom=coord.z, y=coord.y + (out_row + 0.5) / tile_size)
        source_row = int((grid.origin_y - latitude) / grid.pixel_size)
        if not 0 <= source_row < grid.height:
            for buffer in buffers:
                buffer.extend(nodata_row)
            continue
        if source_row != cached_row or cached is None:
            block = dataset.read(
                window=Window(col_off=0, row_off=source_row, width=grid.width, height=1),
                bands=band_indexes,
            )
            cached = block.data
            cached_row = source_row
        for position in range(len(band_indexes)):
            row_data = cached[position]
            buffers[position].extend(row_data[col] if col >= 0 else nodata for col in source_cols)
    return GeneratedTile(coord=coord, tile_size=tile_size, band_indexes=band_indexes, data=buffers)
