"""Story 4 — AreaOfInterest aggregate."""

from __future__ import annotations

import pytest

from app.contexts.earth_observation.domain.aggregates.aoi import AreaOfInterest
from app.shared.domain.enums import EntityStatus, Priority
from app.shared.domain.errors import InvariantViolation, ValueValidationError
from app.shared.domain.events import EntityCreated, EntityUpdated
from app.shared.value_objects.geo import BoundingBox, Coordinates


def _bbox(minlon: float, minlat: float, maxlon: float, maxlat: float) -> BoundingBox:
    return BoundingBox(
        min_longitude=minlon, min_latitude=minlat, max_longitude=maxlon, max_latitude=maxlat
    )


def _make_aoi() -> AreaOfInterest:
    return AreaOfInterest.create(name="Ward 12", bounding_box=_bbox(10.0, 10.0, 12.0, 12.0))


def test_create_defaults_and_event() -> None:
    aoi = _make_aoi()
    assert aoi.status is EntityStatus.ACTIVE
    assert aoi.priority is Priority.MEDIUM
    assert aoi.is_active is True
    events = aoi.pull_events()
    assert len(events) == 1
    assert isinstance(events[0], EntityCreated)


def test_create_requires_name() -> None:
    with pytest.raises(InvariantViolation):
        AreaOfInterest.create(name="  ", bounding_box=_bbox(0.0, 0.0, 1.0, 1.0))


def test_mutations_emit_updated_events() -> None:
    aoi = _make_aoi()
    aoi.pull_events()
    aoi.rename("Ward 13")
    aoi.update_geometry(_bbox(0.0, 0.0, 5.0, 5.0))
    aoi.set_priority(Priority.HIGH)
    aoi.set_revisit_cadence(7)
    aoi.deactivate()
    aoi.activate()
    events = aoi.pull_events()
    assert all(isinstance(e, EntityUpdated) for e in events)
    changed = {f for e in events if isinstance(e, EntityUpdated) for f in e.changed_fields}
    assert {"name", "bounding_box", "priority", "revisit_cadence_days", "status"} <= changed
    assert aoi.name == "Ward 13"
    assert aoi.priority is Priority.HIGH
    assert aoi.revisit_cadence_days == 7


def test_rename_empty_rejected() -> None:
    aoi = _make_aoi()
    with pytest.raises(InvariantViolation):
        aoi.rename("   ")


def test_revisit_cadence_must_be_positive() -> None:
    aoi = _make_aoi()
    with pytest.raises(InvariantViolation):
        aoi.set_revisit_cadence(0)


def test_contains_point() -> None:
    aoi = _make_aoi()
    assert aoi.contains(Coordinates(latitude=11.0, longitude=11.0)) is True
    assert aoi.contains(Coordinates(latitude=50.0, longitude=50.0)) is False


def test_intersects() -> None:
    aoi = _make_aoi()  # 10..12
    assert aoi.intersects(_bbox(11.0, 11.0, 13.0, 13.0)) is True  # overlap
    assert aoi.intersects(_bbox(20.0, 20.0, 21.0, 21.0)) is False  # disjoint


def test_intersects_rejects_srid_mismatch() -> None:
    aoi = _make_aoi()
    other = BoundingBox(
        min_longitude=11.0, min_latitude=11.0, max_longitude=13.0, max_latitude=13.0, srid=3857
    )
    with pytest.raises(ValueValidationError):
        aoi.intersects(other)
