"""Platform service abstractions.

Every service here is defined as a ``Protocol`` (the port), so application code
depends on the interface and never on a concrete integration. Simple in-process
implementations are provided for the ones the platform needs immediately (clock,
id generation, cache, event publishing, in-memory storage/audit); external
integrations (real object storage, search engine, message broker, SMS/email
gateways) are wired in later epics behind these same interfaces.
"""

from app.shared.services.cache import Cache, InMemoryCache
from app.shared.services.clock import Clock, FixedClock, SystemClock
from app.shared.services.id_generator import IdGenerator, Uuid4Generator

__all__ = [
    "Cache",
    "Clock",
    "FixedClock",
    "IdGenerator",
    "InMemoryCache",
    "SystemClock",
    "Uuid4Generator",
]
