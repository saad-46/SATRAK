"""In-memory repository adapters for the Earth Observation aggregates.

Production-capable dev/test adapters over the shared :class:`InMemoryRepository`,
implementing the EO-specific query methods (dedup lookup, AOI listing, and the
``SceneQuery`` search used by the search/history/timeline APIs). Filtering happens in
Python here; a future SQLAlchemy adapter pushes the same ``SceneQuery`` down to PostGIS
without changing a single call site. Scene search results are ordered
newest-acquisition-first.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from app.contexts.earth_observation.domain.aggregates.aoi import AreaOfInterest
from app.contexts.earth_observation.domain.aggregates.scene import Scene
from app.contexts.earth_observation.domain.ports.repositories import SceneQuery
from app.contexts.earth_observation.domain.value_objects.scene_id import ProviderSceneId
from app.shared.domain.enums import EntityStatus
from app.shared.domain.identifiers import EntityId
from app.shared.persistence.repository import InMemoryRepository
from app.shared.value_objects.geo import BoundingBox
from app.shared.value_objects.ranges import TimeRange


def _matches(scene: Scene, query: SceneQuery) -> bool:
    acq = scene.acquisition
    if query.jurisdiction_ids is not None and scene.jurisdiction_id not in query.jurisdiction_ids:
        return False
    if query.statuses and scene.status not in query.statuses:
        return False
    if query.provider is not None and scene.provider_scene_id.provider != query.provider:
        return False
    if query.sensor_type is not None and acq.sensor_type is not query.sensor_type:
        return False
    if query.aoi_id is not None and query.aoi_id not in scene.aoi_ids:
        return False
    if query.window is not None and not _in_window(acq.acquired_at, query.window):
        return False
    if query.area is not None and not _bbox_intersects(scene, query.area):
        return False
    if query.max_cloud_cover_pct is not None:
        cloud = acq.cloud_cover
        if cloud is not None and cloud.value > query.max_cloud_cover_pct:
            return False
    return True


def _in_window(moment: datetime, window: TimeRange) -> bool:
    return window.contains(moment)


def _bbox_intersects(scene: Scene, area: BoundingBox) -> bool:
    box = scene.bounding_box
    if area.srid != box.srid:
        return False
    return not (
        area.min_longitude > box.max_longitude
        or area.max_longitude < box.min_longitude
        or area.min_latitude > box.max_latitude
        or area.max_latitude < box.min_latitude
    )


class InMemorySceneRepository(InMemoryRepository[Scene]):
    """Dict-backed scene repository with dedup, AOI, and criteria search."""

    async def get_by_provider_scene_id(self, provider_scene_id: ProviderSceneId) -> Scene | None:
        for scene in self._store.values():
            if scene.provider_scene_id == provider_scene_id and not scene.is_deleted:
                return scene
        return None

    async def list_for_aoi(
        self, aoi_id: EntityId, *, limit: int = 100, offset: int = 0
    ) -> Sequence[Scene]:
        return await self.search(SceneQuery(aoi_id=aoi_id), limit=limit, offset=offset)

    async def search(
        self, query: SceneQuery, *, limit: int = 100, offset: int = 0
    ) -> Sequence[Scene]:
        matches = self._matching(query)
        return matches[offset : offset + limit]

    async def count_matching(self, query: SceneQuery) -> int:
        return len(self._matching(query))

    def _matching(self, query: SceneQuery) -> list[Scene]:
        matches = [
            scene
            for scene in self._store.values()
            if not scene.is_deleted and _matches(scene, query)
        ]
        # Deterministic newest-first ordering; id as a stable tiebreaker.
        matches.sort(key=lambda s: (s.acquisition.acquired_at, str(s.id)), reverse=True)
        return matches


class InMemoryAoiRepository(InMemoryRepository[AreaOfInterest]):
    """Dict-backed AOI repository with active-listing support."""

    async def list_active(self, *, limit: int = 100, offset: int = 0) -> Sequence[AreaOfInterest]:
        active = [
            aoi
            for aoi in self._store.values()
            if aoi.status is EntityStatus.ACTIVE and not aoi.is_deleted
        ]
        active.sort(key=lambda a: (a.name, str(a.id)))
        return active[offset : offset + limit]
