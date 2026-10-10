"""In-memory persistence adapters: SceneQuery search filters and AOI listing."""

from __future__ import annotations

from datetime import UTC, datetime

from app.contexts.earth_observation.domain.enums import SceneStatus, SensorType
from app.contexts.earth_observation.domain.ports.repositories import SceneQuery
from app.contexts.earth_observation.infrastructure.persistence import (
    InMemoryAoiRepository,
    InMemorySceneRepository,
)
from app.shared.domain.enums import EntityStatus
from app.shared.domain.identifiers import new_id
from app.shared.value_objects.geo import BoundingBox
from app.shared.value_objects.ranges import TimeRange
from tests.contexts.earth_observation.fakes import make_aoi, make_scene

_AREA = BoundingBox(min_longitude=76.0, min_latitude=12.0, max_longitude=78.0, max_latitude=14.0)


async def test_search_filters_and_ordering() -> None:
    repo = InMemorySceneRepository()
    await repo.add(make_scene("OLD"))
    await repo.add(make_scene("NEW"))

    assert await repo.count_matching(SceneQuery()) == 2
    assert await repo.count_matching(SceneQuery(provider="landsat")) == 0
    assert await repo.count_matching(SceneQuery(sensor_type=SensorType.SAR)) == 0
    assert await repo.count_matching(SceneQuery(statuses=frozenset({SceneStatus.AVAILABLE}))) == 0


async def test_search_bbox_srid_mismatch_excludes() -> None:
    repo = InMemorySceneRepository()
    await repo.add(make_scene("S"))
    projected = BoundingBox(
        min_longitude=76.0, min_latitude=12.0, max_longitude=78.0, max_latitude=14.0, srid=3857
    )
    assert await repo.count_matching(SceneQuery(area=projected)) == 0
    assert await repo.count_matching(SceneQuery(area=_AREA)) == 1


async def test_list_for_aoi_and_window() -> None:
    repo = InMemorySceneRepository()
    aoi_id = new_id()
    linked = make_scene("LINKED")
    linked.link_aoi(aoi_id)
    await repo.add(linked)
    await repo.add(make_scene("UNLINKED"))

    for_aoi = await repo.list_for_aoi(aoi_id)
    assert [s.provider_scene_id.native_id for s in for_aoi] == ["LINKED"]

    window = TimeRange(
        start=datetime(2020, 1, 1, tzinfo=UTC), end=datetime(2020, 12, 31, tzinfo=UTC)
    )
    assert await repo.count_matching(SceneQuery(window=window)) == 0  # scenes are 2024


async def test_aoi_list_active() -> None:
    repo = InMemoryAoiRepository()
    active = make_aoi("Ward A")
    inactive = make_aoi("Ward B")
    inactive.deactivate()
    await repo.add(active)
    await repo.add(inactive)

    listed = await repo.list_active()
    assert [a.name for a in listed] == ["Ward A"]
    assert active.status is EntityStatus.ACTIVE


async def test_jurisdiction_scope_filters_and_default_denies() -> None:
    repo = InMemorySceneRepository()
    mine, theirs = new_id(), new_id()
    for native_id, owner in (("A", mine), ("B", theirs)):
        scene = make_scene(native_id)
        scene.jurisdiction_id = owner
        await repo.add(scene)

    assert await repo.count_matching(SceneQuery()) == 2  # unrestricted (trusted internal use)
    assert await repo.count_matching(SceneQuery(jurisdiction_ids=frozenset({mine}))) == 1
    assert await repo.count_matching(SceneQuery(jurisdiction_ids=frozenset({mine, theirs}))) == 2
    assert await repo.count_matching(SceneQuery(jurisdiction_ids=frozenset())) == 0
    assert await repo.count_matching(SceneQuery(jurisdiction_ids=frozenset({new_id()}))) == 0
