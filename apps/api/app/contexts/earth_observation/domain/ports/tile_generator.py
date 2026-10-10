"""Tile generation port.

Contract for producing map tiles for a processed scene; the COG-backed adapter lands in
``infrastructure/tiles`` (Story 14). No implementation here.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from app.contexts.earth_observation.domain.aggregates.scene import Scene
from app.contexts.earth_observation.domain.value_objects.tile import TileCoord, TileMatrixSetRef


@runtime_checkable
class TileGenerator(Protocol):
    """Generates the tile set for a scene on a given tile matrix set."""

    async def generate(
        self, *, scene: Scene, tile_matrix_set: TileMatrixSetRef
    ) -> Sequence[TileCoord]: ...
