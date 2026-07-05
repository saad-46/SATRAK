"""In-memory fake implementations of platform ports, for tests and local dev.

These are the same reference implementations the shared kernel ships, re-exported
under a single ``fakes`` namespace so a test can wire a whole application service
with fakes in one import.
"""

from __future__ import annotations

from app.shared.events.bus import InMemoryEventBus
from app.shared.persistence.repository import InMemoryRepository
from app.shared.persistence.unit_of_work import InMemoryUnitOfWork
from app.shared.services.audit import InMemoryAuditSink
from app.shared.services.background_task import InlineTaskQueue
from app.shared.services.cache import InMemoryCache
from app.shared.services.clock import FixedClock
from app.shared.services.configuration import DictConfigurationProvider
from app.shared.services.notification import NullNotificationSender
from app.shared.services.storage import InMemoryStorageProvider

# Convenience alias — "fake" reads better than "fixed" in some test contexts.
FakeClock = FixedClock

__all__ = [
    "DictConfigurationProvider",
    "FakeClock",
    "FixedClock",
    "InMemoryAuditSink",
    "InMemoryCache",
    "InMemoryEventBus",
    "InMemoryRepository",
    "InMemoryStorageProvider",
    "InMemoryUnitOfWork",
    "InlineTaskQueue",
    "NullNotificationSender",
]
