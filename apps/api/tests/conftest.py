"""Shared pytest fixtures.

Tests build the app via the factory with a TEST environment so they never touch a
real database — the foundation's endpoints under test (liveness, version) have no
datastore dependency.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.config import Environment, Settings
from app.main import create_app
from app.testing.fakes import (
    FixedClock,
    InMemoryCache,
    InMemoryEventBus,
    InMemoryStorageProvider,
    InMemoryUnitOfWork,
)


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings(environment=Environment.TEST, log_format="console")


@pytest_asyncio.fixture
async def client(settings: Settings) -> AsyncIterator[AsyncClient]:
    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# --- Reusable platform fakes -------------------------------------------------
@pytest.fixture
def event_bus() -> InMemoryEventBus:
    return InMemoryEventBus()


@pytest.fixture
def unit_of_work(event_bus: InMemoryEventBus) -> InMemoryUnitOfWork:
    return InMemoryUnitOfWork(event_bus)


@pytest.fixture
def cache() -> InMemoryCache:
    return InMemoryCache()


@pytest.fixture
def storage() -> InMemoryStorageProvider:
    return InMemoryStorageProvider()


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(datetime(2026, 7, 5, 12, 0, tzinfo=UTC))
