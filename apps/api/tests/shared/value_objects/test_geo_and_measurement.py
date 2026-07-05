"""Tests for geospatial and measurement value objects."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.shared.domain.errors import ValueValidationError
from app.shared.value_objects import (
    Area,
    AreaUnit,
    BoundingBox,
    Coordinates,
    Dimensions,
    Distance,
    DistanceUnit,
    GeoPoint,
)


class TestCoordinates:
    def test_valid_and_wkt(self) -> None:
        c = Coordinates(latitude=12.97, longitude=77.59)
        assert c.to_wkt() == "POINT(77.59 12.97)"

    @pytest.mark.parametrize(
        ("lat", "lon"),
        [(91, 0), (-91, 0), (0, 181), (0, -181)],
    )
    def test_out_of_range(self, lat: float, lon: float) -> None:
        with pytest.raises(ValueValidationError):
            Coordinates(latitude=lat, longitude=lon)


class TestGeoPoint:
    def test_defaults_to_wgs84(self) -> None:
        p = GeoPoint(coordinates=Coordinates(latitude=1.0, longitude=2.0))
        assert p.srid == 4326
        assert p.latitude == 1.0
        assert p.longitude == 2.0


class TestBoundingBox:
    def test_center_and_contains(self) -> None:
        bbox = BoundingBox(min_longitude=0, min_latitude=0, max_longitude=10, max_latitude=10)
        assert bbox.center == Coordinates(latitude=5, longitude=5)
        assert bbox.contains(Coordinates(latitude=5, longitude=5)) is True
        assert bbox.contains(Coordinates(latitude=20, longitude=20)) is False
        assert bbox.width_deg == 10
        assert "POLYGON" in bbox.to_wkt()

    def test_min_greater_than_max_rejected(self) -> None:
        with pytest.raises(ValueValidationError):
            BoundingBox(min_longitude=10, min_latitude=0, max_longitude=0, max_latitude=10)


class TestMeasurements:
    def test_distance_conversion(self) -> None:
        assert Distance(Decimal("1"), DistanceUnit.KILOMETER).meters == Decimal("1000")
        assert Distance(Decimal("1"), DistanceUnit.MILE).meters == Decimal("1609.344")

    def test_area_conversion(self) -> None:
        assert Area(Decimal("1"), AreaUnit.HECTARE).square_meters == Decimal("10000")

    def test_negative_rejected(self) -> None:
        with pytest.raises(ValueValidationError):
            Distance(Decimal("-1"))

    def test_dimensions_volume(self) -> None:
        d = Dimensions(length_m=Decimal("2"), width_m=Decimal("3"), height_m=Decimal("4"))
        assert d.volume_cubic_meters == Decimal("24")
