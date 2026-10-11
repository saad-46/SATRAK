"""Tile generation engine (Epic 3 Story 14).

XYZ tile math + windowed, deterministic tile rendering. HTTP tile *serving* arrives in
Story 18; nothing here exposes an endpoint.
"""

from __future__ import annotations

from app.contexts.earth_observation.infrastructure.tiles.renderer import (
    GeneratedTile,
    render_tile,
)
from app.contexts.earth_observation.infrastructure.tiles.tile_matrix import (
    MAX_MERCATOR_LATITUDE,
    lonlat_to_tile,
    tile_bounds_wgs84,
    tile_row_latitude,
    tiles_covering,
)

__all__ = [
    "MAX_MERCATOR_LATITUDE",
    "GeneratedTile",
    "lonlat_to_tile",
    "render_tile",
    "tile_bounds_wgs84",
    "tile_row_latitude",
    "tiles_covering",
]
