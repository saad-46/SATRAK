"""Scope-bound repository view for jurisdiction-owned aggregates (ADR-0011).

The request path never touches a raw repository: it wraps one in a :class:`ScopedRepository`
that is constructed with a mandatory :class:`~app.shared.domain.scope.AccessScope`. Reads of an
existing row outside the scope raise :class:`~app.shared.domain.scope.OutOfScopeError` (mapped to
the 403 contract by the endpoint), and writes are refused when either the stored row or the new
state belongs to a jurisdiction the scope does not allow. A missing row is ``None`` as usual.
"""

from __future__ import annotations

from typing import Protocol

from app.shared.domain.errors import DomainError
from app.shared.domain.identifiers import EntityId
from app.shared.domain.scope import AccessScope, OutOfScopeError
from app.shared.persistence.repository import Repository


class JurisdictionOwned(Protocol):
    @property
    def id(self) -> EntityId: ...

    @property
    def jurisdiction_id(self) -> EntityId: ...


class ScopedRepository[T: JurisdictionOwned]:
    def __init__(self, repository: Repository[T], scope: AccessScope) -> None:  # type: ignore[type-var]
        if not isinstance(scope, AccessScope):
            raise TypeError("a ScopedRepository needs an AccessScope")
        self._repository = repository
        self._scope = scope

    def _check(self, jurisdiction_id: EntityId | None) -> None:
        if not self._scope.allows(jurisdiction_id):
            raise OutOfScopeError(jurisdiction_id)

    async def get(self, entity_id: EntityId) -> T | None:
        entity = await self._repository.get(entity_id)
        if entity is not None:
            self._check(entity.jurisdiction_id)
        return entity

    async def require(self, entity_id: EntityId) -> T:
        entity = await self.get(entity_id)
        if entity is None:
            raise DomainError(f"entity {entity_id} not found")
        return entity

    async def add(self, entity: T) -> T:
        self._check(entity.jurisdiction_id)
        return await self._repository.add(entity)

    async def update(self, entity: T) -> T:
        existing = await self._repository.get(entity.id)
        if existing is not None:
            self._check(existing.jurisdiction_id)  # cannot modify a foreign row
        self._check(entity.jurisdiction_id)  # nor move a row into a foreign jurisdiction
        return await self._repository.update(entity)

    async def delete(self, entity_id: EntityId) -> None:
        existing = await self._repository.get(entity_id)
        if existing is not None:
            self._check(existing.jurisdiction_id)
        await self._repository.delete(entity_id)
