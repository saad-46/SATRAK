"""API-test fixtures (auto-discovered by pytest)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.api.v1.endpoints.earth_observation.composition import EarthObservationApi
from app.core.config import Settings
from app.main import create_app
from tests.auth_support import TestIdp


@pytest_asyncio.fixture
async def eo_env(
    settings: Settings, idp: TestIdp
) -> AsyncIterator[tuple[AsyncClient, EarthObservationApi]]:
    """An app + client whose Earth Observation container the test can seed directly."""
    app = create_app(settings, auth=idp.runtime(settings.auth))
    container: EarthObservationApi = app.state.earth_observation
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=idp.bearer()) as ac:
        yield ac, container
