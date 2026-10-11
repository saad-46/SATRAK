"""Story 4 — Earth Observation endpoints enforce permissions per jurisdiction (A3, A4)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.api.v1.endpoints.earth_observation.composition import EarthObservationApi
from app.core.config import Settings
from app.main import create_app
from tests.api.eo_support import (
    HOME,
    OTHER,
    make_aoi,
    make_available_scene,
    store_tile,
)
from tests.auth_support import TEST_ISSUER, TestIdp
from tests.authz_support import MemoryWorld

ALL = ["eo:scene:read", "eo:aoi:read", "eo:tile:read"]


@dataclass
class Env:
    client: AsyncClient
    idp: TestIdp
    eo: EarthObservationApi
    home_scene: uuid.UUID
    other_scene: uuid.UUID
    home_aoi: uuid.UUID
    other_aoi: uuid.UUID

    def as_(self, subject: str) -> dict[str, str]:
        return self.idp.bearer(claims={"sub": subject})


@pytest_asyncio.fixture
async def env(settings: Settings, idp: TestIdp) -> AsyncIterator[Env]:
    world = MemoryWorld()
    parent = await world.jurisdiction("PARENT", "national")
    for child in (HOME, OTHER):
        world.store.parents[child] = parent
    full = await world.role("full", ALL)
    scenes_only = await world.role("scenes-only", ["eo:scene:read"])
    grants = [
        ("alice", full, HOME),
        ("bob", full, OTHER),
        ("parent-admin", full, parent),
        ("scenes-only", scenes_only, HOME),
        ("nobody", None, None),
    ]
    for subject, role, where in grants:
        uid = await world.user(subject)
        world.store.users[uid] = (TEST_ISSUER, subject, "active")
        if role is not None and where is not None:
            await world.assign(uid, role, where)

    app = create_app(
        settings, auth=idp.runtime(settings.auth), access=world.store, audit=world.audit
    )
    eo: EarthObservationApi = app.state.earth_observation
    home_scene = make_available_scene(native_id="HOME_1", jurisdiction_id=HOME)
    other_scene = make_available_scene(native_id="OTHER_1", jurisdiction_id=OTHER)
    home_aoi, other_aoi = (
        make_aoi("Home ward", jurisdiction_id=HOME),
        make_aoi("Other ward", jurisdiction_id=OTHER),
    )
    for scene in (home_scene, other_scene):
        await eo.scenes.add(scene)
        await store_tile(eo, scene=scene, z=1, x=0, y=0)
    for aoi in (home_aoi, other_aoi):
        await eo.aois.add(aoi)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield Env(client, idp, eo, home_scene.id, other_scene.id, home_aoi.id, other_aoi.id)


async def _get(env: Env, subject: str, path: str) -> tuple[int, dict[str, object]]:
    response = await env.client.get(f"/api/v1/eo{path}", headers=env.as_(subject))
    body = response.json() if response.content else {}
    return response.status_code, body


# --- Lists and searches are restricted to permitted jurisdictions ---------------------------
async def test_scene_search_returns_only_permitted_jurisdictions(env: Env) -> None:
    for subject, expected in (("alice", env.home_scene), ("bob", env.other_scene)):
        status, body = await _get(env, subject, "/scenes")
        assert status == 200
        assert [item["id"] for item in body["items"]] == [str(expected)]  # type: ignore[index, union-attr]


async def test_parent_jurisdiction_sees_descendants(env: Env) -> None:
    status, body = await _get(env, "parent-admin", "/scenes")
    assert status == 200
    ids = {item["id"] for item in body["items"]}  # type: ignore[index, union-attr]
    assert ids == {str(env.home_scene), str(env.other_scene)}


async def test_aoi_list_is_filtered(env: Env) -> None:
    status, body = await _get(env, "alice", "/aoi")
    assert status == 200
    assert [i["id"] for i in body["items"]] == [str(env.home_aoi)]  # type: ignore[index, union-attr]


async def test_area_timeline_is_filtered(env: Env) -> None:
    status, body = await _get(env, "bob", "/timeline?bbox=76,12,78,14")
    assert status == 200
    assert [s["id"] for s in body["scenes"]] == [str(env.other_scene)]  # type: ignore[index, union-attr]


# --- Object access across jurisdictions is denied (A3) --------------------------------------
@pytest.mark.parametrize("suffix", ["", "/status", "/metadata"])
async def test_foreign_scene_is_forbidden(env: Env, suffix: str) -> None:
    status, body = await _get(env, "alice", f"/scenes/{env.other_scene}{suffix}")
    assert status == 403
    assert body["code"] == "forbidden"
    # Only the problem document: no scene attributes leak through the denial.
    assert set(body) <= {"type", "title", "status", "detail", "instance", "code", "request_id"}


async def test_own_scene_is_readable_and_missing_scene_is_404(env: Env) -> None:
    assert (await _get(env, "alice", f"/scenes/{env.home_scene}"))[0] == 200
    assert (await _get(env, "alice", f"/scenes/{uuid.uuid4()}"))[0] == 404


async def test_foreign_aoi_and_its_timeline_are_forbidden(env: Env) -> None:
    assert (await _get(env, "alice", f"/aoi/{env.other_aoi}"))[0] == 403
    assert (await _get(env, "alice", f"/aoi/{env.other_aoi}/timeline"))[0] == 403
    assert (await _get(env, "alice", f"/aoi/{env.home_aoi}"))[0] == 200
    assert (await _get(env, "alice", f"/aoi/{env.home_aoi}/timeline"))[0] == 200


# --- Tiles enforce the same checks (A4) -----------------------------------------------------
async def test_tiles_are_jurisdiction_scoped(env: Env) -> None:
    own = f"/scenes/{env.home_scene}/tiles/1/0/0"
    foreign = f"/scenes/{env.other_scene}/tiles/1/0/0"
    assert (await env.client.get(f"/api/v1/eo{own}", headers=env.as_("alice"))).status_code == 200
    for path in (foreign, f"{foreign}/metadata"):
        response = await env.client.get(f"/api/v1/eo{path}", headers=env.as_("alice"))
        assert response.status_code == 403, path
        assert response.content != b"tile-bytes"
    # A conditional request cannot probe a foreign tile's ETag either.
    probe = await env.client.get(
        f"/api/v1/eo{foreign}", headers={**env.as_("alice"), "If-None-Match": '"x"'}
    )
    assert probe.status_code == 403


# --- Permissions are separate and default-deny ----------------------------------------------
async def test_user_without_assignment_is_denied_everywhere(env: Env) -> None:
    paths = [
        "/scenes",
        f"/scenes/{env.home_scene}",
        f"/scenes/{env.home_scene}/tiles/1/0/0",
        "/aoi",
        f"/aoi/{env.home_aoi}",
        "/timeline?bbox=76,12,78,14",
    ]
    for path in paths:
        assert (await _get(env, "nobody", path))[0] == 403, path


async def test_scene_permission_does_not_grant_tiles_or_aois(env: Env) -> None:
    assert (await _get(env, "scenes-only", "/scenes"))[0] == 200
    assert (await _get(env, "scenes-only", f"/scenes/{env.home_scene}/tiles/1/0/0"))[0] == 403
    assert (await _get(env, "scenes-only", "/aoi"))[0] == 403


async def test_unauthenticated_requests_still_get_401(env: Env) -> None:
    response = await env.client.get("/api/v1/eo/scenes")
    assert response.status_code == 401
