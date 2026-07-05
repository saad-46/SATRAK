"""Tests for the event bus, repositories, unit of work, and pagination."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.shared.domain.entity import AggregateRoot
from app.shared.domain.events import DomainEvent, EntityCreated
from app.shared.domain.identifiers import new_id
from app.shared.events.bus import InMemoryEventBus
from app.shared.pagination import Page, PageRequest, Sort, SortDirection
from app.shared.persistence.repository import InMemoryRepository
from app.shared.persistence.unit_of_work import InMemoryUnitOfWork


@dataclass(kw_only=True, eq=False)
class _Widget(AggregateRoot):
    name: str = "w"


class TestEventBus:
    async def test_routes_to_matching_handlers(self) -> None:
        bus = InMemoryEventBus()
        received: list[str] = []
        bus.subscribe(EntityCreated, lambda e: received.append(e.name))
        await bus.publish(EntityCreated(aggregate_id=new_id(), aggregate_type="Widget"))
        assert received == ["EntityCreated"]

    async def test_base_subscription_catches_subclasses(self) -> None:
        bus = InMemoryEventBus()
        seen: list[str] = []
        bus.subscribe(DomainEvent, lambda e: seen.append(e.name))
        await bus.publish(EntityCreated(aggregate_id=new_id(), aggregate_type="X"))
        assert seen == ["EntityCreated"]

    async def test_supports_async_handlers(self) -> None:
        bus = InMemoryEventBus()
        seen: list[str] = []

        async def handler(e: DomainEvent) -> None:
            seen.append(e.name)

        bus.subscribe(DomainEvent, handler)
        await bus.publish(DomainEvent())
        assert seen == ["DomainEvent"]


class TestInMemoryRepository:
    async def test_add_get_list_count(self) -> None:
        repo: InMemoryRepository[_Widget] = InMemoryRepository()
        widget = _Widget(name="a")
        await repo.add(widget)
        assert await repo.get(widget.id) is widget
        assert await repo.exists(widget.id) is True
        assert await repo.count() == 1
        assert list(await repo.list()) == [widget]

    async def test_soft_deleted_hidden(self) -> None:
        repo: InMemoryRepository[_Widget] = InMemoryRepository()
        widget = _Widget()
        await repo.add(widget)
        widget.soft_delete()
        assert await repo.get(widget.id) is None
        assert await repo.count() == 0


class TestUnitOfWork:
    async def test_commit_dispatches_events(self) -> None:
        bus = InMemoryEventBus()
        published: list[str] = []
        bus.subscribe(DomainEvent, lambda e: published.append(e.name))

        widget = _Widget()
        widget.record_event(EntityCreated(aggregate_id=widget.id, aggregate_type="Widget"))

        async with InMemoryUnitOfWork(bus) as uow:
            uow.track(widget)
            await uow.commit()

        assert published == ["EntityCreated"]
        assert widget.has_pending_events is False

    async def test_rollback_discards_events(self) -> None:
        bus = InMemoryEventBus()
        published: list[str] = []
        bus.subscribe(DomainEvent, lambda e: published.append(e.name))
        widget = _Widget()
        widget.record_event(EntityCreated(aggregate_id=widget.id, aggregate_type="Widget"))

        with pytest.raises(RuntimeError):
            async with InMemoryUnitOfWork(bus) as uow:
                uow.track(widget)
                raise RuntimeError("boom")

        assert published == []


class TestPagination:
    def test_offset_and_pages(self) -> None:
        req = PageRequest(page=3, size=10)
        assert req.offset == 20
        page = Page.create(items=list(range(10)), total=95, request=req)
        assert page.total_pages == 10
        assert page.has_next is True
        assert page.has_previous is True

    def test_validation(self) -> None:
        from app.shared.domain.errors import ValueValidationError

        with pytest.raises(ValueValidationError):
            PageRequest(page=0)
        with pytest.raises(ValueValidationError):
            PageRequest(size=10_000)

    def test_sort_defaults(self) -> None:
        assert Sort(field="name").direction == SortDirection.ASC
