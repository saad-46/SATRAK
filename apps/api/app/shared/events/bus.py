"""Event bus abstraction.

The bus decouples the code that raises a domain event from the code that reacts
to it. The interface is deliberately broker-agnostic: :class:`InMemoryEventBus`
is used in-process (and in tests) now, and a Kafka/RabbitMQ-backed implementation
can be dropped in later without touching a single publisher or handler — the
whole point of Epic 2's abstractions.

Handlers may be sync or async; the bus awaits coroutine handlers and calls plain
ones directly. Subscribing to a base event type (e.g. ``DomainEvent``) receives
every subclass, enabling cross-cutting handlers such as an audit logger.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Iterable
from typing import Protocol, runtime_checkable

from app.shared.domain.events import DomainEvent

EventHandler = Callable[[DomainEvent], None] | Callable[[DomainEvent], Awaitable[None]]


@runtime_checkable
class EventBus(Protocol):
    """Publish/subscribe interface for domain events."""

    def subscribe(self, event_type: type[DomainEvent], handler: EventHandler) -> None: ...

    async def publish(self, event: DomainEvent) -> None: ...

    async def publish_all(self, events: Iterable[DomainEvent]) -> None: ...


class InMemoryEventBus:
    """Synchronous, in-process event bus. Handlers run in registration order."""

    def __init__(self) -> None:
        self._handlers: list[tuple[type[DomainEvent], EventHandler]] = []

    def subscribe(self, event_type: type[DomainEvent], handler: EventHandler) -> None:
        self._handlers.append((event_type, handler))

    async def publish(self, event: DomainEvent) -> None:
        for event_type, handler in self._handlers:
            if isinstance(event, event_type):
                result = handler(event)
                if inspect.isawaitable(result):
                    await result

    async def publish_all(self, events: Iterable[DomainEvent]) -> None:
        for event in events:
            await self.publish(event)
