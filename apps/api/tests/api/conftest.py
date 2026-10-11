"""API-test fixtures (auto-discovered by pytest)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.api.v1.endpoints.earth_observation.composition import EarthObservationApi
from app.core.config import Settings
from app.main import create_app
from tests.api.eo_support import HOME, OTHER
from tests.auth_support import TEST_ISSUER, TestIdp
from tests.authz_support import MemoryWorld

EO_PERMISSIONS = ["eo:scene:read", "eo:aoi:read", "eo:tile:read"]


async def eo_world(subject: str = "user-123") -> MemoryWorld:
    """``subject`` holds every EO read permission in HOME only; OTHER is a sibling tenant."""
    world = MemoryWorld()
    for jid in (HOME, OTHER):
        world.store.parents[jid] = None
    uid = await world.user(subject)
    world.store.users[uid] = (TEST_ISSUER, subject, "active")
    await world.assign(uid, await world.role("officer", EO_PERMISSIONS), HOME)
    return world


@pytest_asyncio.fixture
async def eo_env(
    settings: Settings, idp: TestIdp
) -> AsyncIterator[tuple[AsyncClient, EarthObservationApi]]:
    """An app + client whose Earth Observation container the test can seed directly."""
    world = await eo_world()
    app = create_app(
        settings, auth=idp.runtime(settings.auth), access=world.store, audit=world.audit
    )
    container: EarthObservationApi = app.state.earth_observation
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=idp.bearer()) as ac:
        yield ac, container
