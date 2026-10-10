"""Coordinate-reference-system reference (EPSG code)."""

from __future__ import annotations

from dataclasses import dataclass

from app.shared.domain.errors import ValueValidationError
from app.shared.domain.value_object import ValueObject
from app.shared.value_objects.geo import WGS84_SRID

WEB_MERCATOR_SRID = 3857


@dataclass(frozen=True)
class CrsRef(ValueObject):
    """A reference to a coordinate reference system by EPSG code.

    Storage-agnostic: the platform stores/computes in a national projected CRS and
    interchanges in WGS84 (spec §0.2, Blueprint Part 5). This VO names a CRS; the actual
    transform is done by the ``py-geo`` boundary, not here.
    """

    epsg: int

    def __post_init__(self) -> None:
        if self.epsg <= 0:
            raise ValueValidationError("epsg must be a positive integer", field="epsg")

    @property
    def is_wgs84(self) -> bool:
        return self.epsg == WGS84_SRID

    @property
    def authority_code(self) -> str:
        return f"EPSG:{self.epsg}"

    @classmethod
    def wgs84(cls) -> CrsRef:
        return cls(epsg=WGS84_SRID)

    @classmethod
    def web_mercator(cls) -> CrsRef:
        return cls(epsg=WEB_MERCATOR_SRID)
