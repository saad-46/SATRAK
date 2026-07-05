"""Shared pytest fixtures.

Tests build the app via the factory with a TEST environment so they never touch a
real database — the foundation's endpoints under test (liveness, version) have no
datastore dependency.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.config import Environment, Settings
from app.main import create_app


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings(environment=Environment.TEST, log_format="console")


@pytest_asyncio.fixture
async def client(settings: Settings) -> AsyncIterator[AsyncClient]:
    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
