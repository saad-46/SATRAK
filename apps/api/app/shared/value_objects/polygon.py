"""Polygon geometry value object: structural validation of client-supplied GeoJSON.

This is the *first* gate for a vector geometry (ADR-0012: EPSG:4326 longitude/latitude). It
checks only what can be decided without a spatial engine: shape, finite 2-D numbers, ranges,
closed rings and a bound on size (so a request cannot ask the server to process an unbounded
polygon). Topological validity (self-intersection and the like) is decided by PostGIS at the
persistence boundary, which is the authority for spatial correctness.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Any, Final

from app.shared.domain.errors import ValueValidationError

MAX_POLYGONS: Final = 50
MAX_RINGS_PER_POLYGON: Final = 20
MAX_VERTICES: Final = 5_000
_MIN_RING_POSITIONS: Final = 4
_MIN_RING_AREA: Final = 1e-14  # square degrees; rejects collapsed rings

Position = tuple[float, float]
Ring = tuple[Position, ...]


@dataclass(frozen=True, slots=True)
class GeoPolygon:
    """One or more polygons (exterior ring first, then holes), WGS84 lon/lat."""

    polygons: tuple[tuple[Ring, ...], ...]

    @property
    def vertex_count(self) -> int:
        return sum(len(ring) for rings in self.polygons for ring in rings)

    def to_multipolygon_geojson(self) -> dict[str, Any]:
        return {
            "type": "MultiPolygon",
            "coordinates": [
                [[[lon, lat] for lon, lat in ring] for ring in rings] for rings in self.polygons
            ],
        }

    def to_polygon_geojson(self) -> dict[str, Any]:
        """GeoJSON ``Polygon`` for a single-polygon shape (raises when there are several)."""
        if len(self.polygons) != 1:
            raise ValueValidationError("expected a single polygon", field="geometry")
        return {
            "type": "Polygon",
            "coordinates": [[[lon, lat] for lon, lat in ring] for ring in self.polygons[0]],
        }


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueValidationError("coordinates must be numbers", field=field)
    number = float(value)
    if not math.isfinite(number):
        raise ValueValidationError("coordinates must be finite", field=field)
    return number


def _position(raw: object, field: str) -> Position:
    if not isinstance(raw, Sequence) or isinstance(raw, str | bytes) or len(raw) != 2:
        raise ValueValidationError("a position must be [longitude, latitude]", field=field)
    lon, lat = _number(raw[0], field), _number(raw[1], field)
    if not -180.0 <= lon <= 180.0:
        raise ValueValidationError("longitude must be within [-180, 180]", field=field)
    if not -90.0 <= lat <= 90.0:
        raise ValueValidationError("latitude must be within [-90, 90]", field=field)
    return (lon, lat)


def _signed_area(ring: Ring) -> float:
    total = 0.0
    for (x1, y1), (x2, y2) in pairwise(ring):
        total += x1 * y2 - x2 * y1
    return total / 2.0


def _ring(raw: object, field: str) -> Ring:
    if not isinstance(raw, Sequence) or isinstance(raw, str | bytes):
        raise ValueValidationError("a ring must be a list of positions", field=field)
    if len(raw) < _MIN_RING_POSITIONS:
        raise ValueValidationError("a ring needs at least four positions", field=field)
    ring = tuple(_position(p, field) for p in raw)
    if ring[0] != ring[-1]:
        raise ValueValidationError("a ring must be closed (first == last position)", field=field)
    if abs(_signed_area(ring)) < _MIN_RING_AREA:
        raise ValueValidationError("a ring must enclose an area", field=field)
    return ring


def _polygon(raw: object, field: str) -> tuple[Ring, ...]:
    if not isinstance(raw, Sequence) or isinstance(raw, str | bytes) or not raw:
        raise ValueValidationError("a polygon needs at least an exterior ring", field=field)
    if len(raw) > MAX_RINGS_PER_POLYGON:
        raise ValueValidationError("a polygon has too many rings", field=field)
    return tuple(_ring(r, field) for r in raw)


def parse_polygon_geojson(
    data: object, *, allow_multi: bool, field: str = "geometry"
) -> GeoPolygon:
    """Validate a GeoJSON ``Polygon`` (or ``MultiPolygon`` when ``allow_multi``)."""
    if not isinstance(data, Mapping):
        raise ValueValidationError("geometry must be a GeoJSON object", field=field)
    kind = data.get("type")
    coordinates = data.get("coordinates")
    if kind == "Polygon":
        polygons: tuple[tuple[Ring, ...], ...] = (_polygon(coordinates, field),)
    elif kind == "MultiPolygon" and allow_multi:
        if (
            not isinstance(coordinates, Sequence)
            or isinstance(coordinates, str | bytes)
            or not coordinates
        ):
            raise ValueValidationError("a MultiPolygon needs at least one polygon", field=field)
        if len(coordinates) > MAX_POLYGONS:
            raise ValueValidationError("a MultiPolygon has too many polygons", field=field)
        polygons = tuple(_polygon(p, field) for p in coordinates)
    else:
        allowed = "Polygon or MultiPolygon" if allow_multi else "Polygon"
        raise ValueValidationError(f"geometry type must be {allowed}", field=field)
    shape = GeoPolygon(polygons)
    if shape.vertex_count > MAX_VERTICES:
        raise ValueValidationError(f"geometry has more than {MAX_VERTICES} vertices", field=field)
    return shape
