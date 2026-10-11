"""Structural validation of client-supplied GeoJSON polygons (shared kernel)."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from app.shared.domain.errors import ValueValidationError
from app.shared.value_objects.polygon import (
    MAX_POLYGONS,
    MAX_VERTICES,
    parse_polygon_geojson,
)

SQUARE: dict[str, Any] = {
    "type": "Polygon",
    "coordinates": [[[77.0, 12.0], [77.001, 12.0], [77.001, 12.001], [77.0, 12.001], [77.0, 12.0]]],
}


def test_a_valid_polygon_round_trips() -> None:
    shape = parse_polygon_geojson(SQUARE, allow_multi=False)
    assert shape.vertex_count == 5
    assert shape.to_polygon_geojson()["coordinates"] == SQUARE["coordinates"]
    multi = shape.to_multipolygon_geojson()
    assert multi["type"] == "MultiPolygon"
    assert multi["coordinates"] == [SQUARE["coordinates"]]


def test_multipolygon_is_accepted_only_when_allowed() -> None:
    multi = {"type": "MultiPolygon", "coordinates": [SQUARE["coordinates"]]}
    assert len(parse_polygon_geojson(multi, allow_multi=True).polygons) == 1
    with pytest.raises(ValueValidationError, match=r"must be Polygon$"):
        parse_polygon_geojson(multi, allow_multi=False)


def test_a_multi_shape_cannot_be_read_as_a_single_polygon() -> None:
    two = {"type": "MultiPolygon", "coordinates": [SQUARE["coordinates"], SQUARE["coordinates"]]}
    shape = parse_polygon_geojson(two, allow_multi=True)
    with pytest.raises(ValueValidationError, match="single polygon"):
        shape.to_polygon_geojson()


@pytest.mark.parametrize(
    "bad",
    [
        None,
        "polygon",
        {"type": "Point", "coordinates": [1, 2]},
        {"type": "Polygon"},
        {"type": "Polygon", "coordinates": []},
        {"type": "Polygon", "coordinates": "x"},
        {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [0, 0]]]},  # too few positions
        {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1]]]},  # not closed
        {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [2, 0], [0, 0]]]},  # no area
        {"type": "Polygon", "coordinates": [[[0, 0, 5], [1, 0, 5], [1, 1, 5], [0, 0, 5]]]},
        {"type": "Polygon", "coordinates": [[[181, 0], [1, 0], [1, 1], [181, 0]]]},
        {"type": "Polygon", "coordinates": [[[0, 91], [1, 0], [1, 1], [0, 91]]]},
        {"type": "Polygon", "coordinates": [[["a", 0], [1, 0], [1, 1], ["a", 0]]]},
        {"type": "Polygon", "coordinates": [[[True, 0], [1, 0], [1, 1], [True, 0]]]},
        {"type": "Polygon", "coordinates": [[[float("nan"), 0], [1, 0], [1, 1], [0, 0]]]},
        {"type": "Polygon", "coordinates": [[[float("inf"), 0], [1, 0], [1, 1], [0, 0]]]},
        {"type": "Polygon", "coordinates": [["ab", [1, 0], [1, 1], "ab"]]},
        {"type": "Polygon", "coordinates": ["ring"]},
    ],
)
def test_malformed_geometry_is_rejected(bad: object) -> None:
    with pytest.raises(ValueValidationError):
        parse_polygon_geojson(bad, allow_multi=True)


def test_size_limits_bound_the_work_a_request_can_demand() -> None:
    many = {"type": "MultiPolygon", "coordinates": [SQUARE["coordinates"]] * (MAX_POLYGONS + 1)}
    with pytest.raises(ValueValidationError, match="too many polygons"):
        parse_polygon_geojson(many, allow_multi=True)
    ring = [[i * 1e-6, 0.0] for i in range(MAX_VERTICES)] + [[0.0, 1.0], [0.0, 0.0]]
    with pytest.raises(ValueValidationError, match="vertices"):
        parse_polygon_geojson({"type": "Polygon", "coordinates": [ring]}, allow_multi=False)
    holes = copy.deepcopy(SQUARE)
    holes["coordinates"] = holes["coordinates"] * 21
    with pytest.raises(ValueValidationError, match="too many rings"):
        parse_polygon_geojson(holes, allow_multi=False)
    with pytest.raises(ValueValidationError, match="at least one polygon"):
        parse_polygon_geojson({"type": "MultiPolygon", "coordinates": []}, allow_multi=True)
