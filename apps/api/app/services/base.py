"""Service layer foundation.

Services own business rules and coordinate repositories within a unit of work.
The base class simply holds the session so concrete services in bounded contexts
share a consistent construction contract. No domain logic lives here yet.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession


class BaseService:
    """Base class for application services."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
