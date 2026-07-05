"""Unit of Work abstraction.

The Unit of Work defines an atomic boundary: either all changes within it commit,
or none do. It also owns *domain-event dispatch* — aggregates mutated in the
transaction are registered, and their events are collected and published only
after a successful commit. This guarantees no event escapes for a change that was
rolled back (the classic "dual write" problem), and keeps event publishing out of
the domain model itself.

:class:`InMemoryUnitOfWork` supports tests; :class:`SqlAlchemyUnitOfWork` wraps an
``AsyncSession``. Both share the commit → collect → publish flow via
:class:`AbstractUnitOfWork`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from types import TracebackType
from typing import Protocol, runtime_checkable

from app.shared.domain.entity import AggregateRoot
from app.shared.domain.events import DomainEvent
from app.shared.events.bus import EventBus


@runtime_checkable
class UnitOfWork(Protocol):
    """Atomic transaction boundary with post-commit event dispatch."""

    async def __aenter__(self) -> UnitOfWork: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...

    def track(self, aggregate: AggregateRoot) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class AbstractUnitOfWork(ABC):
    """Shared commit/rollback + event-collection logic."""

    def __init__(self, event_bus: EventBus | None = None) -> None:
        self._event_bus = event_bus
        self._tracked: list[AggregateRoot] = []

    async def __aenter__(self) -> AbstractUnitOfWork:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        # Roll back automatically if the block raised and wasn't committed.
        if exc_type is not None:
            await self.rollback()

    def track(self, aggregate: AggregateRoot) -> None:
        """Register an aggregate so its events dispatch after commit."""
        if aggregate not in self._tracked:
            self._tracked.append(aggregate)

    def _collect_events(self) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        for aggregate in self._tracked:
            events.extend(aggregate.pull_events())
        self._tracked.clear()
        return events

    async def commit(self) -> None:
        await self._commit()
        events = self._collect_events()
        if self._event_bus is not None:
            await self._event_bus.publish_all(events)

    async def rollback(self) -> None:
        self._tracked.clear()
        await self._rollback()

    @abstractmethod
    async def _commit(self) -> None: ...

    @abstractmethod
    async def _rollback(self) -> None: ...


class InMemoryUnitOfWork(AbstractUnitOfWork):
    """No-op persistence; still performs event collection/dispatch. For tests."""

    def __init__(self, event_bus: EventBus | None = None) -> None:
        super().__init__(event_bus)
        self.committed = False

    async def _commit(self) -> None:
        self.committed = True

    async def _rollback(self) -> None:
        self.committed = False


class SqlAlchemyUnitOfWork(AbstractUnitOfWork):
    """Wraps a SQLAlchemy ``AsyncSession`` as the transactional boundary."""

    def __init__(self, session: object, event_bus: EventBus | None = None) -> None:
        super().__init__(event_bus)
        # Typed as object to keep this module import-light; the real session is an
        # sqlalchemy.ext.asyncio.AsyncSession injected by the infrastructure layer.
        self._session = session

    async def _commit(self) -> None:
        await self._session.commit()  # type: ignore[attr-defined]

    async def _rollback(self) -> None:
        await self._session.rollback()  # type: ignore[attr-defined]
