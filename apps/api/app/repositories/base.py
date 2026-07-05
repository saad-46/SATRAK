"""Generic async repository foundation.

Provides reusable CRUD primitives over a SQLAlchemy model so concrete
repositories in bounded contexts inherit a consistent data-access surface. This
is infrastructure plumbing only — it contains no domain rules (those belong in
the service layer).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base


class BaseRepository[ModelType: Base]:
    """Async CRUD repository parameterized by an ORM model type."""

    def __init__(self, model: type[ModelType], session: AsyncSession) -> None:
        self.model = model
        self.session = session

    async def get(self, entity_id: UUID) -> ModelType | None:
        return await self.session.get(self.model, entity_id)

    async def list(self, *, limit: int = 100, offset: int = 0) -> Sequence[ModelType]:
        result = await self.session.execute(
            select(self.model).limit(limit).offset(offset)
        )
        return result.scalars().all()

    async def count(self) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(self.model)
        )
        return int(result.scalar_one())

    async def add(self, entity: ModelType) -> ModelType:
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def update(self, entity: ModelType, values: dict[str, Any]) -> ModelType:
        for key, value in values.items():
            setattr(entity, key, value)
        await self.session.flush()
        return entity

    async def delete(self, entity_id: UUID) -> None:
        await self.session.execute(
            delete(self.model).where(self.model.id == entity_id)  # type: ignore[attr-defined]
        )
