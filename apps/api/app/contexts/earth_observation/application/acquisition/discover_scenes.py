"""Scene discovery orchestration (Epic 3 Story 10).

Searches a provider for candidate scenes over an AOI + time window, filters and
deduplicates them, registers the survivors as ``Scene`` aggregates (recording
``ImageDiscovered``), and hands each new scene off to the ingestion pipeline via the
shared ``TaskQueue`` port. Events dispatch through the Unit of Work on commit
(ADR-0002); the hand-off is enqueued only *after* a successful commit so no ghost
tasks exist for rolled-back scenes.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.contexts.earth_observation.application.dto import DiscoveryResult
from app.contexts.earth_observation.domain.aggregates.aoi import AreaOfInterest
from app.contexts.earth_observation.domain.aggregates.scene import Scene
from app.contexts.earth_observation.domain.ports.imagery_provider import (
    EarthObservationProvider,
    SceneCandidate,
)
from app.contexts.earth_observation.domain.ports.repositories import SceneRepository
from app.shared.persistence.unit_of_work import UnitOfWork
from app.shared.services.background_task import BackgroundTask, TaskQueue
from app.shared.value_objects.ranges import TimeRange

INGEST_SCENE_TASK = "earth_observation.ingest_scene"


@dataclass(frozen=True)
class DiscoveryFilter:
    """Candidate acceptance policy applied before a scene is registered."""

    max_cloud_cover_pct: float | None = None
    require_aoi_intersection: bool = True

    def accepts(self, candidate: SceneCandidate, *, aoi: AreaOfInterest) -> bool:
        cloud = candidate.acquisition.cloud_cover
        if (
            self.max_cloud_cover_pct is not None
            and cloud is not None
            and cloud.value > self.max_cloud_cover_pct
        ):
            return False
        return not (self.require_aoi_intersection and not aoi.intersects(candidate.bounding_box))


class SceneDiscoveryService:
    """Discovers, filters, deduplicates, and registers scenes for an AOI."""

    def __init__(
        self,
        *,
        provider: EarthObservationProvider,
        scenes: SceneRepository,
        uow: UnitOfWork,
        task_queue: TaskQueue | None = None,
        discovery_filter: DiscoveryFilter | None = None,
    ) -> None:
        self._provider = provider
        self._scenes = scenes
        self._uow = uow
        self._task_queue = task_queue
        self._filter = discovery_filter if discovery_filter is not None else DiscoveryFilter()

    async def discover(self, *, aoi: AreaOfInterest, window: TimeRange) -> DiscoveryResult:
        candidates = await self._provider.search(area=aoi.bounding_box, window=window)

        created: list[Scene] = []
        filtered_out = 0
        duplicates = 0
        for candidate in candidates:
            if not self._filter.accepts(candidate, aoi=aoi):
                filtered_out += 1
                continue
            existing = await self._scenes.get_by_provider_scene_id(candidate.provider_scene_id)
            if existing is not None:
                duplicates += 1
                continue
            scene = Scene.create(
                provider_scene_id=candidate.provider_scene_id,
                bounding_box=candidate.bounding_box,
                acquisition=candidate.acquisition,
                jurisdiction_id=aoi.jurisdiction_id,
            )
            scene.link_aoi(aoi.id)
            await self._scenes.add(scene)
            self._uow.track(scene)
            created.append(scene)

        await self._uow.commit()

        # Hand-off happens only after the scenes are durably registered.
        if self._task_queue is not None:
            for scene in created:
                await self._task_queue.enqueue(
                    BackgroundTask(name=INGEST_SCENE_TASK, payload={"scene_id": str(scene.id)})
                )

        return DiscoveryResult(
            scene_ids=tuple(scene.id for scene in created),
            duplicates=duplicates,
            filtered_out=filtered_out,
        )
