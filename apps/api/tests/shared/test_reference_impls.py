"""Tests for reference implementations that back the platform ports.

Closes coverage gaps on the in-process adapters (event publisher, task queue,
audit sink, null notifier) and the TimeRange value object — the pieces future
modules wire in for local/dev/test runs.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.shared.domain.errors import ValueValidationError
from app.shared.domain.events import DomainEvent
from app.shared.events.bus import InMemoryEventBus
from app.shared.services.audit import AuditEntry, InMemoryAuditSink
from app.shared.services.background_task import BackgroundTask, InlineTaskQueue
from app.shared.services.event_publisher import BusEventPublisher
from app.shared.services.notification import (
    NotificationChannel,
    NotificationMessage,
    NullNotificationSender,
)
from app.shared.value_objects.ranges import TimeRange


class TestBusEventPublisher:
    async def test_publish_and_publish_all_bridge_to_bus(self) -> None:
        bus = InMemoryEventBus()
        seen: list[str] = []
        bus.subscribe(DomainEvent, lambda e: seen.append(e.name))
        publisher = BusEventPublisher(bus)

        await publisher.publish(DomainEvent())
        await publisher.publish_all([DomainEvent(), DomainEvent()])
        assert len(seen) == 3


class TestInlineTaskQueue:
    async def test_runs_registered_sync_and_async_handlers(self) -> None:
        queue = InlineTaskQueue()
        calls: list[str] = []

        queue.register("sync", lambda t: calls.append(f"sync:{t.payload['x']}"))

        async def async_handler(t: BackgroundTask) -> None:
            calls.append("async")

        queue.register("async", async_handler)

        await queue.enqueue(BackgroundTask(name="sync", payload={"x": 1}))
        await queue.enqueue(BackgroundTask(name="async"))
        await queue.enqueue(BackgroundTask(name="unregistered"))

        assert calls == ["sync:1", "async"]
        assert len(queue.enqueued) == 3  # all enqueues recorded, even unhandled


class TestInMemoryAuditSink:
    async def test_records_entries(self) -> None:
        sink = InMemoryAuditSink()
        from app.shared.domain.identifiers import new_id

        await sink.record(AuditEntry(action="viewed", subject_type="Case", subject_id=new_id()))
        assert len(sink.entries) == 1
        assert sink.entries[0].action == "viewed"


class TestNullNotificationSender:
    async def test_send_is_noop(self) -> None:
        sender = NullNotificationSender()
        result = await sender.send(
            NotificationMessage(
                channel=NotificationChannel.EMAIL,
                recipient="a@b.com",
                subject="s",
                body="b",
            )
        )
        assert result is None


class TestTimeRange:
    def test_duration_contains_overlaps(self) -> None:
        start = datetime(2026, 7, 5, 9, 0, tzinfo=UTC)
        end = start + timedelta(hours=2)
        tr = TimeRange(start=start, end=end)
        assert tr.duration_seconds == 7200
        assert tr.contains(start + timedelta(hours=1)) is True
        assert tr.contains(end + timedelta(hours=1)) is False

        overlapping = TimeRange(start=start + timedelta(hours=1), end=end + timedelta(hours=1))
        disjoint = TimeRange(start=end + timedelta(hours=1), end=end + timedelta(hours=2))
        assert tr.overlaps(overlapping) is True
        assert tr.overlaps(disjoint) is False

    def test_start_after_end_rejected(self) -> None:
        start = datetime(2026, 7, 5, 9, 0, tzinfo=UTC)
        with pytest.raises(ValueValidationError):
            TimeRange(start=start, end=start - timedelta(hours=1))
