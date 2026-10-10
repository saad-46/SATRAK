"""Direct repository-boundary tests: missing scope, cross-jurisdiction reads and writes."""

from __future__ import annotations

import ast
import pathlib
import uuid

import pytest

from app.contexts.earth_observation.domain.aggregates.aoi import AreaOfInterest
from app.contexts.earth_observation.infrastructure.persistence import (
    InMemoryAoiRepository,
    InMemorySceneRepository,
)
from app.shared.domain.scope import OutOfScopeError, TenantScope
from app.shared.domain.system_scope import SystemScope
from app.shared.persistence.scoped import ScopedRepository
from tests.api.eo_support import make_aoi, make_available_scene

MINE = uuid.uuid4()
THEIRS = uuid.uuid4()
SCOPE = TenantScope(frozenset({MINE}))


def _aoi(jurisdiction: uuid.UUID) -> AreaOfInterest:
    return make_aoi("AOI", jurisdiction_id=jurisdiction)


def test_a_scope_is_mandatory_and_must_be_an_access_scope() -> None:
    with pytest.raises(TypeError):
        ScopedRepository(InMemoryAoiRepository())  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        ScopedRepository(InMemoryAoiRepository(), None)  # type: ignore[arg-type]


async def test_get_missing_is_none_and_foreign_raises_out_of_scope() -> None:
    raw = InMemoryAoiRepository()
    mine, theirs = _aoi(MINE), _aoi(THEIRS)
    await raw.add(mine)
    await raw.add(theirs)
    view = ScopedRepository(raw, SCOPE)
    assert await view.get(mine.id) is mine
    assert await view.get(uuid.uuid4()) is None
    with pytest.raises(OutOfScopeError) as caught:
        await view.get(theirs.id)
    assert caught.value.jurisdiction_id == THEIRS
    with pytest.raises(OutOfScopeError):
        await view.require(theirs.id)


async def test_an_empty_tenant_scope_reaches_nothing() -> None:
    raw = InMemoryAoiRepository()
    aoi = _aoi(MINE)
    await raw.add(aoi)
    with pytest.raises(OutOfScopeError):
        await ScopedRepository(raw, TenantScope(frozenset())).get(aoi.id)


async def test_writes_into_or_over_a_foreign_jurisdiction_are_refused() -> None:
    raw = InMemoryAoiRepository()
    theirs = _aoi(THEIRS)
    await raw.add(theirs)
    view = ScopedRepository(raw, SCOPE)
    with pytest.raises(OutOfScopeError):
        await view.add(_aoi(THEIRS))  # create in a foreign jurisdiction
    with pytest.raises(OutOfScopeError):
        await view.update(theirs)  # modify a foreign row
    with pytest.raises(OutOfScopeError):
        await view.delete(theirs.id)  # delete a foreign row
    assert await raw.get(theirs.id) is theirs  # nothing changed

    mine = _aoi(MINE)
    await view.add(mine)
    mine.jurisdiction_id = THEIRS  # try to move an owned row into a foreign jurisdiction
    with pytest.raises(OutOfScopeError):
        await view.update(mine)
    mine.jurisdiction_id = MINE
    await view.update(mine)
    await view.delete(mine.id)
    assert await raw.get(mine.id) is None


async def test_scene_view_and_system_scope() -> None:
    raw = InMemorySceneRepository()
    scene = make_available_scene(native_id="S1", jurisdiction_id=THEIRS)
    await raw.add(scene)
    with pytest.raises(OutOfScopeError):
        await ScopedRepository(raw, SCOPE).get(scene.id)
    system = ScopedRepository(raw, SystemScope("test: scoped repository system read"))
    assert await system.get(scene.id) is scene


def test_request_handlers_reach_tenant_data_only_through_scoped_views() -> None:
    """Architecture guard: endpoints may not call unscoped ``eo.scenes``/``eo.aois`` methods."""
    allowed = {"list_in_scope", "count_in_scope"}  # scope is a required argument of these
    root = pathlib.Path(__file__).resolve().parents[3] / "app" / "api"
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Attribute)
                and node.value.attr in {"scenes", "aois"}
                and isinstance(node.value.value, ast.Name)
                and node.value.value.id == "eo"
                and node.attr not in allowed
            ):
                offenders.append(f"{path.name}:{node.lineno} eo.{node.value.attr}.{node.attr}")
    assert offenders == []
