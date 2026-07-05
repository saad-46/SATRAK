"""Geospatial value objects: Coordinates, GeoPoint, BoundingBox.

These are the foundation of every spatial feature in SATRAK. They are transport-
and storage-agnostic (no GeoAlchemy/Shapely dependency); the GIS infrastructure
layer converts them to/from PostGIS geometries. WGS84 (EPSG:4326) is the default
interchange CRS, matching the platform convention (geometry stored in a national
projected CRS, exchanged as WGS84 — see TDD §6).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.shared.domain.errors import ValueValidationError
from app.shared.domain.value_object import ValueObject

WGS84_SRID = 4326

_MIN_LAT, _MAX_LAT = -90.0, 90.0
_MIN_LON, _MAX_LON = -180.0, 180.0


@dataclass(frozen=True)
class Coordinates(ValueObject):
    """A latitude/longitude pair in decimal degrees (WGS84)."""

    latitude: float
    longitude: float

    def __post_init__(self) -> None:
        if not _MIN_LAT <= self.latitude <= _MAX_LAT:
            raise ValueValidationError(
                f"latitude {self.latitude} out of range [-90, 90]", field="latitude"
            )
        if not _MIN_LON <= self.longitude <= _MAX_LON:
            raise ValueValidationError(
                f"longitude {self.longitude} out of range [-180, 180]", field="longitude"
            )

    def to_wkt(self) -> str:
        """WKT uses (x y) = (lon lat) ordering."""
        return f"POINT({self.longitude} {self.latitude})"


@dataclass(frozen=True)
class GeoPoint(ValueObject):
    """A spatial point: coordinates plus optional altitude and an SRID."""

    coordinates: Coordinates
    altitude_m: float | None = None
    srid: int = WGS84_SRID

    def __post_init__(self) -> None:
        if self.srid <= 0:
            raise ValueValidationError("srid must be a positive integer", field="srid")

    @property
    def latitude(self) -> float:
        return self.coordinates.latitude

    @property
    def longitude(self) -> float:
        return self.coordinates.longitude


@dataclass(frozen=True)
class BoundingBox(ValueObject):
    """An axis-aligned lon/lat extent (min corner to max corner)."""

    min_longitude: float
    min_latitude: float
    max_longitude: float
    max_latitude: float
    srid: int = field(default=WGS84_SRID)

    def __post_init__(self) -> None:
        for name, lat in (("min_latitude", self.min_latitude), ("max_latitude", self.max_latitude)):
            if not _MIN_LAT <= lat <= _MAX_LAT:
                raise ValueValidationError(f"{name} out of range [-90, 90]", field=name)
        for name, lon in (
            ("min_longitude", self.min_longitude),
            ("max_longitude", self.max_longitude),
        ):
            if not _MIN_LON <= lon <= _MAX_LON:
                raise ValueValidationError(f"{name} out of range [-180, 180]", field=name)
        if self.min_longitude > self.max_longitude:
            raise ValueValidationError("min_longitude must be <= max_longitude")
        if self.min_latitude > self.max_latitude:
            raise ValueValidationError("min_latitude must be <= max_latitude")

    @property
    def width_deg(self) -> float:
        return self.max_longitude - self.min_longitude

    @property
    def height_deg(self) -> float:
        return self.max_latitude - self.min_latitude

    @property
    def center(self) -> Coordinates:
        return Coordinates(
            latitude=(self.min_latitude + self.max_latitude) / 2,
            longitude=(self.min_longitude + self.max_longitude) / 2,
        )

    def contains(self, point: Coordinates) -> bool:
        return (
            self.min_longitude <= point.longitude <= self.max_longitude
            and self.min_latitude <= point.latitude <= self.max_latitude
        )

    def to_wkt(self) -> str:
        return (
            "POLYGON(("
            f"{self.min_longitude} {self.min_latitude}, "
            f"{self.max_longitude} {self.min_latitude}, "
            f"{self.max_longitude} {self.max_latitude}, "
            f"{self.min_longitude} {self.max_latitude}, "
            f"{self.min_longitude} {self.min_latitude}))"
        )
