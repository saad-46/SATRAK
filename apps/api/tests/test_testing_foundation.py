"""Smoke tests for the reusable testing foundation (factories + fakes + fixtures)."""

from __future__ import annotations

from app.testing import factories
from app.testing.fakes import InMemoryCache, InMemoryEventBus, InMemoryUnitOfWork


def test_factories_build_valid_objects() -> None:
    org = factories.make_organization()
    assert org.code == "TMC"
    assert factories.make_user_profile().email.value == "officer@example.gov"
    assert factories.make_role().code == "officer"
    assert factories.make_task().title == "Test task"


async def test_fixtures_are_wired(
    event_bus: InMemoryEventBus,
    unit_of_work: InMemoryUnitOfWork,
    cache: InMemoryCache,
) -> None:
    assert isinstance(event_bus, InMemoryEventBus)
    await cache.set("k", 1)
    assert await cache.get("k") == 1
    async with unit_of_work as uow:
        await uow.commit()
    assert unit_of_work.committed is True


def test_clock_fixture_is_frozen(clock: object) -> None:
    from app.testing.fakes import FixedClock

    assert isinstance(clock, FixedClock)
    assert clock.now() == clock.now()
