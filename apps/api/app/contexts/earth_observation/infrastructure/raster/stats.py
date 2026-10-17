"""Chunked raster statistics and histograms (Epic 3 Story 12).

Both computations stream the dataset in row-band chunks (``iter_windows``) and keep
O(1)/O(bins) state, so they run in bounded memory over arbitrarily large rasters.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.contexts.earth_observation.infrastructure.raster.dataset import RasterDataset
from app.contexts.earth_observation.infrastructure.raster.grid import iter_windows
from app.shared.domain.errors import ValueValidationError


@dataclass(frozen=True)
class BandStatistics:
    minimum: float
    maximum: float
    mean: float
    std_dev: float
    count: int


@dataclass(frozen=True)
class Histogram:
    """Fixed-range histogram; values outside ``[lower, upper)`` are ignored."""

    lower: float
    upper: float
    counts: tuple[int, ...]

    @property
    def total(self) -> int:
        return sum(self.counts)


def compute_statistics(
    dataset: RasterDataset, *, band: int, chunk_height: int = 256
) -> BandStatistics:
    """Single-pass min/max/mean/std via sum + sum-of-squares accumulation."""
    total = 0
    acc = 0.0
    acc_sq = 0.0
    minimum = math.inf
    maximum = -math.inf
    for window in iter_windows(
        dataset.grid, tile_width=dataset.grid.width, tile_height=chunk_height
    ):
        block = dataset.read(window=window, bands=(band,))
        for value in block.data[0]:
            total += 1
            acc += value
            acc_sq += value * value
            minimum = min(minimum, value)
            maximum = max(maximum, value)
    if total == 0:  # unreachable with valid grids (>=1 pixel); defensive
        raise ValueValidationError("cannot compute statistics of an empty raster", field="band")
    mean = acc / total
    variance = max(0.0, acc_sq / total - mean * mean)
    return BandStatistics(
        minimum=minimum,
        maximum=maximum,
        mean=mean,
        std_dev=math.sqrt(variance),
        count=total,
    )


def compute_histogram(
    dataset: RasterDataset,
    *,
    band: int,
    bins: int,
    lower: float,
    upper: float,
    chunk_height: int = 256,
) -> Histogram:
    if bins < 1:
        raise ValueValidationError("bins must be >= 1", field="bins")
    if not upper > lower:
        raise ValueValidationError("upper must be > lower", field="range")
    counts = [0] * bins
    scale = bins / (upper - lower)
    for window in iter_windows(
        dataset.grid, tile_width=dataset.grid.width, tile_height=chunk_height
    ):
        block = dataset.read(window=window, bands=(band,))
        for value in block.data[0]:
            if lower <= value < upper:
                counts[int((value - lower) * scale)] += 1
    return Histogram(lower=lower, upper=upper, counts=tuple(counts))
