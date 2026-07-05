"""Repository abstraction.

A repository is a collection-like interface over aggregates; it hides the storage
mechanism from the domain. The :class:`Repository` protocol is the contract every
concrete (SQLAlchemy, in-memory) repository honours, so application services
depend on the abstraction, never on a database. :class:`InMemoryRepository` is a
fully working implementation used by tests and for prototyping a context before
its persistence layer exists.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from app.shared.domain.entity import Entity
from app.shared.domain.identifiers import EntityId


@runtime_checkable
class Repository[T: Entity](Protocol):
    """Async, collection-oriented persistence contract for an aggregate type."""

    async def get(self, entity_id: EntityId) -> T | None: ...

    async def require(self, entity_id: EntityId) -> T: ...

    async def add(self, entity: T) -> T: ...

    async def update(self, entity: T) -> T: ...

    async def delete(self, entity_id: EntityId) -> None: ...

    async def exists(self, entity_id: EntityId) -> bool: ...

    async def list(self, *, limit: int = 100, offset: int = 0) -> Sequence[T]: ...

    async def count(self) -> int: ...


class InMemoryRepository[T: Entity]:
    """Dict-backed repository. Honours soft-delete (``list`` hides deleted rows)."""

    def __init__(self) -> None:
        self._store: dict[EntityId, T] = {}

    async def get(self, entity_id: EntityId) -> T | None:
        entity = self._store.get(entity_id)
        if entity is None or entity.is_deleted:
            return None
        return entity

    async def require(self, entity_id: EntityId) -> T:
        entity = await self.get(entity_id)
        if entity is None:
            from app.shared.domain.errors import DomainError

            raise DomainError(f"entity {entity_id} not found")
        return entity

    async def add(self, entity: T) -> T:
        self._store[entity.id] = entity
        return entity

    async def update(self, entity: T) -> T:
        self._store[entity.id] = entity
        return entity

    async def delete(self, entity_id: EntityId) -> None:
        self._store.pop(entity_id, None)

    async def exists(self, entity_id: EntityId) -> bool:
        return await self.get(entity_id) is not None

    async def list(self, *, limit: int = 100, offset: int = 0) -> Sequence[T]:
        live = [e for e in self._store.values() if not e.is_deleted]
        return live[offset : offset + limit]

    async def count(self) -> int:
        return sum(1 for e in self._store.values() if not e.is_deleted)
