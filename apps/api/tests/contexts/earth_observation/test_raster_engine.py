"""Story 12 — raster engine: grids, windows, datasets, stats, ops."""

from __future__ import annotations

import math

import pytest

from app.contexts.earth_observation.domain.value_objects import CrsRef
from app.contexts.earth_observation.infrastructure.raster import (
    CogWriter,
    InMemoryRaster,
    RasterDataset,
    RasterGrid,
    Reprojector,
    Window,
    clip,
    compute_histogram,
    compute_statistics,
    iter_windows,
    minmax_normalize,
    select_bands,
    validate_dataset,
)
from app.shared.domain.errors import ValueValidationError
from app.shared.value_objects.geo import BoundingBox

# A 4x4, 2-band raster anchored at (100, 50) with 1-unit pixels.
_GRID = RasterGrid(
    width=4,
    height=4,
    band_count=2,
    crs=CrsRef.wgs84(),
    origin_x=100.0,
    origin_y=50.0,
    pixel_size=1.0,
)
_BAND0 = [float(v) for v in range(16)]  # 0..15 row-major
_BAND1 = [float(v) * 2 for v in range(16)]


def _raster() -> InMemoryRaster:
    return InMemoryRaster(grid=_GRID, bands=[_BAND0, _BAND1])


# --- Window / grid -----------------------------------------------------------------
def test_window_validation() -> None:
    with pytest.raises(ValueValidationError):
        Window(col_off=-1, row_off=0, width=1, height=1)
    with pytest.raises(ValueValidationError):
        Window(col_off=0, row_off=0, width=0, height=1)


def test_grid_validation_and_bounds() -> None:
    assert _GRID.bounds == (100.0, 46.0, 104.0, 50.0)
    assert _GRID.full_window == Window(col_off=0, row_off=0, width=4, height=4)
    with pytest.raises(ValueValidationError):
        RasterGrid(
            width=0,
            height=1,
            band_count=1,
            crs=CrsRef.wgs84(),
            origin_x=0.0,
            origin_y=0.0,
            pixel_size=1.0,
        )
    with pytest.raises(ValueValidationError):
        RasterGrid(
            width=1,
            height=1,
            band_count=1,
            crs=CrsRef.wgs84(),
            origin_x=0.0,
            origin_y=0.0,
            pixel_size=0.0,
        )


def test_window_for_bbox_and_subgrid() -> None:
    bbox = BoundingBox(
        min_longitude=101.2, min_latitude=47.2, max_longitude=102.8, max_latitude=48.8
    )
    window = _GRID.window_for_bbox(bbox)
    assert window == Window(col_off=1, row_off=1, width=2, height=2)

    sub = _GRID.grid_for_window(window)
    assert (sub.origin_x, sub.origin_y) == (101.0, 49.0)
    assert (sub.width, sub.height) == (2, 2)

    outside = BoundingBox(
        min_longitude=200.0 - 180.0, min_latitude=-10.0, max_longitude=30.0, max_latitude=-5.0
    )
    with pytest.raises(ValueValidationError):
        _GRID.window_for_bbox(outside)


def test_iter_windows_covers_grid_exactly() -> None:
    windows = list(iter_windows(_GRID, tile_width=3, tile_height=3))
    assert [(w.width, w.height) for w in windows] == [(3, 3), (1, 3), (3, 1), (1, 1)]
    assert sum(w.pixel_count for w in windows) == _GRID.pixel_count
    with pytest.raises(ValueValidationError):
        next(iter_windows(_GRID, tile_width=0))


# --- Dataset -------------------------------------------------------------------------
def test_read_full_and_windowed() -> None:
    raster = _raster()
    full = raster.read()
    assert list(full.data[0]) == _BAND0
    assert full.band_indexes == (0, 1)

    window = Window(col_off=1, row_off=1, width=2, height=2)
    block = raster.read(window=window, bands=(1,))
    assert list(block.data[0]) == [10.0, 12.0, 18.0, 20.0]
    assert block.value(band_pos=0, row=0, col=1) == 12.0
    with pytest.raises(ValueValidationError):
        block.value(band_pos=0, row=2, col=0)


def test_read_rejects_bad_window_and_bands() -> None:
    raster = _raster()
    with pytest.raises(ValueValidationError):
        raster.read(window=Window(col_off=3, row_off=0, width=2, height=1))
    with pytest.raises(ValueValidationError):
        raster.read(bands=(5,))


def test_dataset_construction_validation() -> None:
    with pytest.raises(ValueValidationError):
        InMemoryRaster(grid=_GRID, bands=[_BAND0])  # band count mismatch
    with pytest.raises(ValueValidationError):
        InMemoryRaster(grid=_GRID, bands=[_BAND0, [1.0, 2.0]])  # short band


def test_satisfies_protocol() -> None:
    assert isinstance(_raster(), RasterDataset)
    assert CogWriter is not None and Reprojector is not None  # seam contracts exist


# --- Statistics / histogram --------------------------------------------------------------
def test_statistics_known_values() -> None:
    stats = compute_statistics(_raster(), band=0, chunk_height=2)
    assert (stats.minimum, stats.maximum, stats.count) == (0.0, 15.0, 16)
    assert stats.mean == pytest.approx(7.5)
    assert stats.std_dev == pytest.approx(math.sqrt(77.5 - 7.5 * 7.5))  # E[x^2] - mean^2


def test_histogram_counts_and_range() -> None:
    hist = compute_histogram(_raster(), band=0, bins=4, lower=0.0, upper=16.0, chunk_height=2)
    assert hist.counts == (4, 4, 4, 4)
    assert hist.total == 16

    partial = compute_histogram(_raster(), band=0, bins=2, lower=0.0, upper=8.0)
    assert partial.total == 8  # values >= upper are ignored

    with pytest.raises(ValueValidationError):
        compute_histogram(_raster(), band=0, bins=0, lower=0.0, upper=1.0)
    with pytest.raises(ValueValidationError):
        compute_histogram(_raster(), band=0, bins=2, lower=1.0, upper=1.0)


# --- Operations -----------------------------------------------------------------------
def test_select_bands() -> None:
    selected = select_bands(_raster(), bands=(1,))
    assert selected.grid.band_count == 1
    assert list(selected.read().data[0]) == _BAND1
    with pytest.raises(ValueValidationError):
        select_bands(_raster(), bands=())


def test_clip_produces_georeferenced_subraster() -> None:
    bbox = BoundingBox(
        min_longitude=101.0, min_latitude=47.0, max_longitude=103.0, max_latitude=49.0
    )
    clipped = clip(_raster(), bbox=bbox)
    assert (clipped.grid.width, clipped.grid.height) == (2, 2)
    assert (clipped.grid.origin_x, clipped.grid.origin_y) == (101.0, 49.0)
    assert list(clipped.read(bands=(0,)).data[0]) == [5.0, 6.0, 9.0, 10.0]


def test_minmax_normalize() -> None:
    normalized = minmax_normalize(_raster())
    block = normalized.read()
    assert min(block.data[0]) == 0.0
    assert max(block.data[0]) == 1.0
    assert block.data[0][8] == pytest.approx(8 / 15)

    flat = InMemoryRaster(
        grid=RasterGrid(
            width=2,
            height=1,
            band_count=1,
            crs=CrsRef.wgs84(),
            origin_x=0.0,
            origin_y=1.0,
            pixel_size=1.0,
        ),
        bands=[[3.0, 3.0]],
    )
    assert list(minmax_normalize(flat).read().data[0]) == [0.0, 0.0]  # constant band

    with pytest.raises(ValueValidationError):
        minmax_normalize(_raster(), statistics=[compute_statistics(_raster(), band=0)])


def test_validate_dataset_flags_non_finite() -> None:
    assert validate_dataset(_raster()) == ()
    dirty = InMemoryRaster(
        grid=RasterGrid(
            width=2,
            height=2,
            band_count=1,
            crs=CrsRef.wgs84(),
            origin_x=0.0,
            origin_y=2.0,
            pixel_size=1.0,
        ),
        bands=[[1.0, math.nan, math.inf, 4.0]],
    )
    issues = validate_dataset(dirty)
    assert len(issues) == 1
    assert issues[0].code == "non_finite_pixels"
    assert "2 non-finite" in issues[0].message


# --- Edge/defensive branches ----------------------------------------------------------
def test_raster_block_validation() -> None:
    from array import array

    from app.contexts.earth_observation.infrastructure.raster import RasterBlock

    window = Window(col_off=0, row_off=0, width=2, height=1)
    with pytest.raises(ValueValidationError):
        RasterBlock(window=window, band_indexes=(0, 1), data=(array("f", [1.0, 2.0]),))
    with pytest.raises(ValueValidationError):
        RasterBlock(window=window, band_indexes=(0,), data=(array("f", [1.0]),))


def test_grid_rejects_zero_bands_and_bad_subwindow() -> None:
    with pytest.raises(ValueValidationError):
        RasterGrid(
            width=1,
            height=1,
            band_count=0,
            crs=CrsRef.wgs84(),
            origin_x=0.0,
            origin_y=1.0,
            pixel_size=1.0,
        )
    with pytest.raises(ValueValidationError):
        _GRID.grid_for_window(Window(col_off=3, row_off=3, width=2, height=2))


def test_validate_dataset_reports_unreadable_band() -> None:
    class _Broken:
        @property
        def grid(self) -> RasterGrid:
            return _GRID

        def read(self, *, window: Window | None = None, bands: object = None) -> object:
            raise ValueValidationError("simulated read failure", field="window")

    issues = validate_dataset(_Broken())  # type: ignore[arg-type]
    assert {issue.code for issue in issues} == {"unreadable_band"}
    assert len(issues) == _GRID.band_count
