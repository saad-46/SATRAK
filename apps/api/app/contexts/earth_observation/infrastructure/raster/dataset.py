"""Raster datasets: lazy, windowed pixel access (Epic 3 Story 12).

``RasterDataset`` is the engine's data contract — read-only, window-addressed, band-
selectable — so every operation streams chunks instead of materialising whole scenes.
``InMemoryRaster`` is the working in-process implementation (synthetic scenes, tests,
small products); a rasterio/GDAL-backed dataset satisfies the same Protocol when that
dependency is introduced (spec §9), which is how heavy libraries stay out of everything
above this seam.
"""

from __future__ import annotations

from array import array
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.contexts.earth_observation.infrastructure.raster.grid import RasterGrid, Window
from app.shared.domain.errors import ValueValidationError


@dataclass(frozen=True)
class RasterBlock:
    """Pixels for one window: one row-major float array per selected band."""

    window: Window
    band_indexes: tuple[int, ...]
    data: tuple[array[float], ...]

    def __post_init__(self) -> None:
        if len(self.band_indexes) != len(self.data):
            raise ValueValidationError("one data buffer per band required", field="data")
        expected = self.window.pixel_count
        for buffer in self.data:
            if len(buffer) != expected:
                raise ValueValidationError(
                    f"band buffer holds {len(buffer)} pixels, window needs {expected}",
                    field="data",
                )

    def value(self, *, band_pos: int, row: int, col: int) -> float:
        """Pixel value by position within the block (not grid coordinates)."""
        if not (0 <= row < self.window.height and 0 <= col < self.window.width):
            raise ValueValidationError("pixel outside the block window", field="pixel")
        return self.data[band_pos][row * self.window.width + col]


@runtime_checkable
class RasterDataset(Protocol):
    """Read-only, window-addressed raster source."""

    @property
    def grid(self) -> RasterGrid: ...

    def read(
        self, *, window: Window | None = None, bands: Sequence[int] | None = None
    ) -> RasterBlock: ...


class InMemoryRaster:
    """Row-major in-memory raster; reads copy only the requested window."""

    def __init__(self, *, grid: RasterGrid, bands: Sequence[Sequence[float]]) -> None:
        if len(bands) != grid.band_count:
            raise ValueValidationError(
                f"grid declares {grid.band_count} bands, got {len(bands)}", field="bands"
            )
        self._grid = grid
        self._bands: tuple[array[float], ...] = tuple(array("f", band) for band in bands)
        for index, band in enumerate(self._bands):
            if len(band) != grid.pixel_count:
                raise ValueValidationError(
                    f"band {index} holds {len(band)} pixels, grid needs {grid.pixel_count}",
                    field="bands",
                )

    @property
    def grid(self) -> RasterGrid:
        return self._grid

    def read(
        self, *, window: Window | None = None, bands: Sequence[int] | None = None
    ) -> RasterBlock:
        target = window if window is not None else self._grid.full_window
        if not self._grid.contains_window(target):
            raise ValueValidationError("window exceeds the raster extent", field="window")
        band_indexes = tuple(bands) if bands is not None else tuple(range(len(self._bands)))
        for index in band_indexes:
            if not 0 <= index < len(self._bands):
                raise ValueValidationError(f"band index {index} out of range", field="bands")

        buffers: list[array[float]] = []
        for index in band_indexes:
            source = self._bands[index]
            out: array[float] = array("f")
            for row in range(target.row_off, target.row_off + target.height):
                start = row * self._grid.width + target.col_off
                out.extend(source[start : start + target.width])
            buffers.append(out)
        return RasterBlock(window=target, band_indexes=band_indexes, data=tuple(buffers))
