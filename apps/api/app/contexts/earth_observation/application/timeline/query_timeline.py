"""Timeline queries (Epic 3 Story 19).

``RepositoryTimelineProvider`` implements the domain ``TimelineProvider`` port over a
``SceneRepository``: it returns the available scenes whose footprint intersects an area
within a time window, newest-acquisition first (spec §10). The same query serves an AOI's
history (its bounding box) and the property-timeline integration hook (a parcel's bounding
box passed in by the property context) — no per-entity timeline storage; it is a read over
scene references.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.contexts.earth_observation.domain.aggregates.scene import Scene
from app.contexts.earth_observation.domain.enums import SceneStatus
from app.contexts.earth_observation.domain.ports.repositories import SceneQuery, SceneRepository
from app.shared.domain.identifiers import EntityId
from app.shared.value_objects.geo import BoundingBox
from app.shared.value_objects.ranges import TimeRange

_TIMELINE_STATUSES = frozenset({SceneStatus.AVAILABLE})


class RepositoryTimelineProvider:
    """Imagery history over an area, backed by the scene repository."""

    def __init__(
        self,
        *,
        scenes: SceneRepository,
        statuses: frozenset[SceneStatus] = _TIMELINE_STATUSES,
    ) -> None:
        self._scenes = scenes
        self._statuses = statuses

    async def timeline(
        self,
        *,
        area: BoundingBox,
        window: TimeRange,
        limit: int = 100,
        offset: int = 0,
        jurisdiction_ids: frozenset[EntityId] | None = None,
    ) -> Sequence[Scene]:
        return await self._scenes.search(
            SceneQuery(
                area=area,
                window=window,
                statuses=self._statuses,
                jurisdiction_ids=jurisdiction_ids,
            ),
            limit=limit,
            offset=offset,
        )
