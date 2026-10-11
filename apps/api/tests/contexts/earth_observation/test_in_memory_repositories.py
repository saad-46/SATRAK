"""In-memory persistence adapters: SceneQuery search filters and AOI listing."""

from __future__ import annotations

import pathlib
from datetime import UTC, datetime

import pytest

from app.contexts.earth_observation.domain.enums import SceneStatus, SensorType
from app.contexts.earth_observation.domain.ports.repositories import SceneQuery
from app.contexts.earth_observation.infrastructure.persistence import (
    InMemoryAoiRepository,
    InMemorySceneRepository,
)
from app.shared.domain.enums import EntityStatus
from app.shared.domain.identifiers import EntityId, new_id
from app.shared.domain.scope import TenantScope
from app.shared.domain.system_scope import SystemScope
from app.shared.value_objects.geo import BoundingBox
from app.shared.value_objects.ranges import TimeRange
from tests.contexts.earth_observation.fakes import make_aoi, make_scene

_AREA = BoundingBox(min_longitude=76.0, min_latitude=12.0, max_longitude=78.0, max_latitude=14.0)

SYSTEM = SystemScope("repository contract tests")


async def test_search_filters_and_ordering() -> None:
    repo = InMemorySceneRepository()
    await repo.add(make_scene("OLD"))
    await repo.add(make_scene("NEW"))

    assert await repo.count_matching(SceneQuery(scope=SYSTEM)) == 2
    assert await repo.count_matching(SceneQuery(scope=SYSTEM, provider="landsat")) == 0
    assert await repo.count_matching(SceneQuery(scope=SYSTEM, sensor_type=SensorType.SAR)) == 0
    assert (
        await repo.count_matching(
            SceneQuery(scope=SYSTEM, statuses=frozenset({SceneStatus.AVAILABLE}))
        )
        == 0
    )


async def test_search_bbox_srid_mismatch_excludes() -> None:
    repo = InMemorySceneRepository()
    await repo.add(make_scene("S"))
    projected = BoundingBox(
        min_longitude=76.0, min_latitude=12.0, max_longitude=78.0, max_latitude=14.0, srid=3857
    )
    assert await repo.count_matching(SceneQuery(scope=SYSTEM, area=projected)) == 0
    assert await repo.count_matching(SceneQuery(scope=SYSTEM, area=_AREA)) == 1


async def test_list_for_aoi_and_window() -> None:
    repo = InMemorySceneRepository()
    aoi_id = new_id()
    linked = make_scene("LINKED")
    linked.link_aoi(aoi_id)
    await repo.add(linked)
    await repo.add(make_scene("UNLINKED"))

    for_aoi = await repo.list_for_aoi(aoi_id, scope=SYSTEM)
    assert [s.provider_scene_id.native_id for s in for_aoi] == ["LINKED"]

    window = TimeRange(
        start=datetime(2020, 1, 1, tzinfo=UTC), end=datetime(2020, 12, 31, tzinfo=UTC)
    )
    assert (
        await repo.count_matching(SceneQuery(scope=SYSTEM, window=window)) == 0
    )  # scenes are 2024


async def test_aoi_list_active() -> None:
    repo = InMemoryAoiRepository()
    active = make_aoi("Ward A")
    inactive = make_aoi("Ward B")
    inactive.deactivate()
    await repo.add(active)
    await repo.add(inactive)

    listed = await repo.list_in_scope(scope=SYSTEM)
    assert [a.name for a in listed] == ["Ward A"]
    assert await repo.count_in_scope(scope=SYSTEM) == 1
    assert await repo.count_in_scope(scope=SYSTEM, active_only=False) == 2
    # A tenant scope that does not cover the AOI's jurisdiction sees nothing, and paging is
    # applied after scoping.
    empty = TenantScope(frozenset())
    assert await repo.list_in_scope(scope=empty, active_only=False) == []
    assert await repo.count_in_scope(scope=empty) == 0
    assert active.status is EntityStatus.ACTIVE


async def test_jurisdiction_scope_filters_and_default_denies() -> None:
    repo = InMemorySceneRepository()
    mine, theirs = new_id(), new_id()
    for native_id, owner in (("A", mine), ("B", theirs)):
        scene = make_scene(native_id)
        scene.jurisdiction_id = owner
        await repo.add(scene)

    assert (
        await repo.count_matching(SceneQuery(scope=SYSTEM)) == 2
    )  # explicit system scope sees every tenant
    assert await repo.count_matching(SceneQuery(scope=TenantScope(frozenset({mine})))) == 1
    assert await repo.count_matching(SceneQuery(scope=TenantScope(frozenset({mine, theirs})))) == 2
    assert await repo.count_matching(SceneQuery(scope=TenantScope(frozenset()))) == 0
    assert await repo.count_matching(SceneQuery(scope=TenantScope(frozenset({new_id()})))) == 0


def test_a_query_cannot_be_built_without_a_scope() -> None:
    with pytest.raises(TypeError):
        SceneQuery()  # type: ignore[call-arg]


def test_system_scope_needs_a_reason_and_tenant_scope_denies_unknowns() -> None:
    with pytest.raises(ValueError):
        SystemScope("  ")
    scope = TenantScope(frozenset({new_id()}))
    assert not scope.allows(None) and not scope.allows(new_id())
    assert SystemScope("nightly reindex").allows(new_id())


def test_the_web_layer_does_not_import_the_system_scope() -> None:
    root = pathlib.Path(__file__).resolve().parents[3] / "app"
    offenders = [
        str(path.relative_to(root))
        for folder in ("api", "main.py")
        for path in ([root / folder] if folder.endswith(".py") else (root / folder).rglob("*.py"))
        if "system_scope" in path.read_text()
    ]
    assert offenders == []


def test_access_scope_is_sealed_and_scene_query_validates_it() -> None:
    from app.shared.domain.scope import AccessScope

    with pytest.raises(TypeError):

        class _Everything(AccessScope):
            def allows(self, jurisdiction_id: EntityId | None) -> bool:
                return True

    with pytest.raises(TypeError):
        SceneQuery(scope=object())  # type: ignore[arg-type]
