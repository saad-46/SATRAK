"""Slippy-map tile matrix math for WebMercatorQuad (Epic 3 Story 14).

Pure, deterministic XYZ tile addressing over the WGS84 interchange surface: longitude maps
linearly to tile columns; latitude maps through the Web Mercator projection (clamped to
its ±85.05° validity limit). No projection library — these are the standard closed-form
slippy-map formulas, and full CRS warping stays behind the ``Reprojector`` seam.
"""

from __future__ import annotations

import math
from collections.abc import Iterator

from app.contexts.earth_observation.domain.value_objects.tile import TileCoord
from app.shared.value_objects.geo import BoundingBox

MAX_MERCATOR_LATITUDE = 85.05112878


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def lonlat_to_tile(*, longitude: float, latitude: float, zoom: int) -> TileCoord:
    """The tile containing a WGS84 point at ``zoom`` (Mercator-clamped latitude)."""
    n = 1 << zoom
    lon = _clamp(longitude, -180.0, 180.0)
    lat_rad = math.radians(_clamp(latitude, -MAX_MERCATOR_LATITUDE, MAX_MERCATOR_LATITUDE))
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return TileCoord(z=zoom, x=min(x, n - 1), y=min(y, n - 1))


def tile_row_latitude(*, zoom: int, y: float) -> float:
    """The latitude of a fractional tile-row coordinate (used for per-row sampling)."""
    n = 1 << zoom
    return math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * y / n))))


def tile_bounds_wgs84(coord: TileCoord) -> BoundingBox:
    """The WGS84 extent of one XYZ tile."""
    n = 1 << coord.z
    west = coord.x / n * 360.0 - 180.0
    east = (coord.x + 1) / n * 360.0 - 180.0
    north = tile_row_latitude(zoom=coord.z, y=float(coord.y))
    south = tile_row_latitude(zoom=coord.z, y=float(coord.y + 1))
    return BoundingBox(
        min_longitude=west, min_latitude=south, max_longitude=east, max_latitude=north
    )


def tiles_covering(bbox: BoundingBox, *, zoom: int) -> Iterator[TileCoord]:
    """All tiles intersecting a WGS84 bbox at ``zoom``, row-major (deterministic order)."""
    top_left = lonlat_to_tile(longitude=bbox.min_longitude, latitude=bbox.max_latitude, zoom=zoom)
    bottom_right = lonlat_to_tile(
        longitude=bbox.max_longitude, latitude=bbox.min_latitude, zoom=zoom
    )
    for y in range(top_left.y, bottom_right.y + 1):
        for x in range(top_left.x, bottom_right.x + 1):
            yield TileCoord(z=zoom, x=x, y=y)
