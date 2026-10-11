"""Raster geometry: pixel windows and georeferenced grids (Epic 3 Story 12).

A ``Window`` addresses a rectangular pixel region; a ``RasterGrid`` ties pixel space to
map space via a north-up geotransform (top-left origin, square pixels). Windowed
addressing is the foundation of chunked/streaming processing — every engine operation
works window-by-window so imagery never has to fit in memory at once.
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from dataclasses import dataclass

from app.contexts.earth_observation.domain.value_objects.crs import CrsRef
from app.shared.domain.errors import ValueValidationError
from app.shared.value_objects.geo import BoundingBox


@dataclass(frozen=True)
class Window:
    """A rectangular pixel region (column/row offsets + size)."""

    col_off: int
    row_off: int
    width: int
    height: int

    def __post_init__(self) -> None:
        if self.col_off < 0 or self.row_off < 0:
            raise ValueValidationError("window offsets must be >= 0", field="window")
        if self.width < 1 or self.height < 1:
            raise ValueValidationError("window size must be >= 1x1", field="window")

    @property
    def pixel_count(self) -> int:
        return self.width * self.height


@dataclass(frozen=True)
class RasterGrid:
    """Shape + georeferencing of a raster (north-up, square pixels)."""

    width: int
    height: int
    band_count: int
    crs: CrsRef
    origin_x: float
    origin_y: float
    pixel_size: float

    def __post_init__(self) -> None:
        if self.width < 1 or self.height < 1:
            raise ValueValidationError("grid dimensions must be >= 1x1", field="grid")
        if self.band_count < 1:
            raise ValueValidationError("grid needs at least one band", field="band_count")
        if self.pixel_size <= 0:
            raise ValueValidationError("pixel_size must be positive", field="pixel_size")

    @property
    def pixel_count(self) -> int:
        return self.width * self.height

    @property
    def full_window(self) -> Window:
        return Window(col_off=0, row_off=0, width=self.width, height=self.height)

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        """(min_x, min_y, max_x, max_y) in the grid's CRS."""
        return (
            self.origin_x,
            self.origin_y - self.height * self.pixel_size,
            self.origin_x + self.width * self.pixel_size,
            self.origin_y,
        )

    def contains_window(self, window: Window) -> bool:
        return (
            window.col_off + window.width <= self.width
            and window.row_off + window.height <= self.height
        )

    def window_for_bbox(self, bbox: BoundingBox) -> Window:
        """The pixel window covering ``bbox``, clamped to the grid.

        The bbox is interpreted in the grid's CRS (x = longitude axis, y = latitude
        axis) — CRS *transformation* is the ``py-geo`` boundary's job, not the grid's.
        """
        min_x, min_y, max_x, max_y = self.bounds
        if (
            bbox.min_longitude >= max_x
            or bbox.max_longitude <= min_x
            or bbox.min_latitude >= max_y
            or bbox.max_latitude <= min_y
        ):
            raise ValueValidationError("bbox does not intersect the raster extent", field="bbox")
        col_start = max(0, math.floor((bbox.min_longitude - self.origin_x) / self.pixel_size))
        col_end = min(self.width, math.ceil((bbox.max_longitude - self.origin_x) / self.pixel_size))
        row_start = max(0, math.floor((self.origin_y - bbox.max_latitude) / self.pixel_size))
        row_end = min(self.height, math.ceil((self.origin_y - bbox.min_latitude) / self.pixel_size))
        return Window(
            col_off=col_start,
            row_off=row_start,
            width=max(1, col_end - col_start),
            height=max(1, row_end - row_start),
        )

    def grid_for_window(self, window: Window) -> RasterGrid:
        """The georeferenced grid of a sub-window (used by clip/select outputs)."""
        if not self.contains_window(window):
            raise ValueValidationError("window exceeds the grid extent", field="window")
        return RasterGrid(
            width=window.width,
            height=window.height,
            band_count=self.band_count,
            crs=self.crs,
            origin_x=self.origin_x + window.col_off * self.pixel_size,
            origin_y=self.origin_y - window.row_off * self.pixel_size,
            pixel_size=self.pixel_size,
        )


def iter_windows(
    grid: RasterGrid, *, tile_width: int = 256, tile_height: int = 256
) -> Iterator[Window]:
    """Tile the grid into windows for chunked, memory-bounded processing."""
    if tile_width < 1 or tile_height < 1:
        raise ValueValidationError("tile size must be >= 1x1", field="tile")
    for row_off in range(0, grid.height, tile_height):
        for col_off in range(0, grid.width, tile_width):
            yield Window(
                col_off=col_off,
                row_off=row_off,
                width=min(tile_width, grid.width - col_off),
                height=min(tile_height, grid.height - row_off),
            )
