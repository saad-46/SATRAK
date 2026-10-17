"""Read/query services for the Earth Observation APIs (Epic 3 Story 17).

Thin read models over the repository ports — no business logic beyond turning a
``SceneQuery`` + ``PageRequest`` into a paginated ``Page`` (search pushes filtering down
to the repository so a future PostGIS adapter is efficient). Single-scene reads stay on
the repository; these services exist only where pagination or ordering is involved.
"""

from __future__ import annotations

from app.contexts.earth_observation.domain.aggregates.scene import Scene
from app.contexts.earth_observation.domain.ports.repositories import SceneQuery, SceneRepository
from app.shared.pagination import Page, PageRequest


class SceneQueryService:
    """Paginated scene search/history over a :class:`SceneRepository`."""

    def __init__(self, *, scenes: SceneRepository) -> None:
        self._scenes = scenes

    async def search(self, query: SceneQuery, *, request: PageRequest) -> Page[Scene]:
        items = await self._scenes.search(query, limit=request.limit, offset=request.offset)
        total = await self._scenes.count_matching(query)
        return Page.create(list(items), total, request)
