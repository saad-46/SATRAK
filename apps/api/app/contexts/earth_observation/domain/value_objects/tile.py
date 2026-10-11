"""Tile addressing: TileCoord and TileMatrixSetRef."""

from __future__ import annotations

from dataclasses import dataclass

from app.contexts.earth_observation.domain.value_objects.crs import CrsRef
from app.shared.domain.errors import ValueValidationError
from app.shared.domain.value_object import ValueObject

WEB_MERCATOR_QUAD = "WebMercatorQuad"


@dataclass(frozen=True)
class TileCoord(ValueObject):
    """An XYZ/WMTS tile address ``(z, x, y)``.

    ``x`` and ``y`` are constrained to the valid range for the zoom level
    (``0 <= x, y < 2**z``) — the standard slippy-map grid.
    """

    z: int
    x: int
    y: int

    def __post_init__(self) -> None:
        if self.z < 0:
            raise ValueValidationError("zoom z must be >= 0", field="z")
        span = 1 << self.z
        if not 0 <= self.x < span:
            raise ValueValidationError(f"x must be in [0, {span}) for z={self.z}", field="x")
        if not 0 <= self.y < span:
            raise ValueValidationError(f"y must be in [0, {span}) for z={self.z}", field="y")

    def __str__(self) -> str:
        return f"{self.z}/{self.x}/{self.y}"

    def parent(self) -> TileCoord | None:
        """The tile one zoom level up that contains this one, or ``None`` at z=0."""
        if self.z == 0:
            return None
        return TileCoord(z=self.z - 1, x=self.x // 2, y=self.y // 2)


@dataclass(frozen=True)
class TileMatrixSetRef(ValueObject):
    """A named tile matrix set (grid definition) with its CRS."""

    identifier: str
    crs: CrsRef

    def __post_init__(self) -> None:
        identifier = self.identifier.strip()
        if not identifier:
            raise ValueValidationError("tile matrix set identifier is required", field="identifier")
        object.__setattr__(self, "identifier", identifier)

    @classmethod
    def web_mercator_quad(cls) -> TileMatrixSetRef:
        return cls(identifier=WEB_MERCATOR_QUAD, crs=CrsRef.web_mercator())
