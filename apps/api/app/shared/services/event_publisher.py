"""Event publisher service.

A narrow outbound port for emitting domain/integration events. It is distinct
from :class:`~app.shared.events.bus.EventBus` (which also handles subscription):
application code that only needs to *emit* depends on this thinner interface.
:class:`BusEventPublisher` bridges it to whatever bus is configured.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, runtime_checkable

from app.shared.domain.events import DomainEvent
from app.shared.events.bus import EventBus


@runtime_checkable
class EventPublisher(Protocol):
    async def publish(self, event: DomainEvent) -> None: ...

    async def publish_all(self, events: Iterable[DomainEvent]) -> None: ...


class BusEventPublisher:
    """Adapts an :class:`EventBus` to the :class:`EventPublisher` port."""

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus

    async def publish(self, event: DomainEvent) -> None:
        await self._bus.publish(event)

    async def publish_all(self, events: Iterable[DomainEvent]) -> None:
        await self._bus.publish_all(events)
