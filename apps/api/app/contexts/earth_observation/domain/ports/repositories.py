"""Repository ports for the Earth Observation aggregates.

They extend the shared-kernel :class:`~app.shared.persistence.repository.Repository`
contract (DRY) with the EO-specific lookups the application/API layers need. Concrete
SQLAlchemy adapters land in ``infrastructure/persistence`` (a future story); an in-memory
adapter ships now for dev/tests. ``SceneQuery`` lives here (not the application layer) so
the domain port can reference it without breaking domain-layer purity.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from app.contexts.earth_observation.domain.aggregates.aoi import AreaOfInterest
from app.contexts.earth_observation.domain.aggregates.scene import Scene
from app.contexts.earth_observation.domain.enums import SceneStatus, SensorType
from app.contexts.earth_observation.domain.value_objects.scene_id import ProviderSceneId
from app.shared.domain.identifiers import EntityId
from app.shared.persistence.repository import Repository
from app.shared.value_objects.geo import BoundingBox
from app.shared.value_objects.ranges import TimeRange


@dataclass(frozen=True)
class SceneQuery:
    """Search criteria for scenes; every field is an optional, ANDed filter.

    ``area`` matches scenes whose footprint bounding box intersects it (WGS84);
    ``window`` matches by acquisition time; ``statuses`` restricts lifecycle state.
    Results are ordered newest-acquisition first — the natural order for history and
    timeline views (spec §10).
    """

    area: BoundingBox | None = None
    window: TimeRange | None = None
    statuses: frozenset[SceneStatus] = field(default_factory=frozenset)
    provider: str | None = None
    sensor_type: SensorType | None = None
    max_cloud_cover_pct: float | None = None
    aoi_id: EntityId | None = None
    # Jurisdiction scope: ``None`` = unrestricted (trusted internal callers only); an empty
    # set matches nothing (default deny); otherwise rows must belong to one of the ids.
    jurisdiction_ids: frozenset[EntityId] | None = None


@runtime_checkable
class SceneRepository(Repository[Scene], Protocol):
    """Persistence contract for :class:`Scene` aggregates."""

    async def get_by_provider_scene_id(
        self, provider_scene_id: ProviderSceneId
    ) -> Scene | None: ...

    async def list_for_aoi(
        self, aoi_id: EntityId, *, limit: int = 100, offset: int = 0
    ) -> Sequence[Scene]: ...

    async def search(
        self, query: SceneQuery, *, limit: int = 100, offset: int = 0
    ) -> Sequence[Scene]: ...

    async def count_matching(self, query: SceneQuery) -> int: ...


@runtime_checkable
class AoiRepository(Repository[AreaOfInterest], Protocol):
    """Persistence contract for :class:`AreaOfInterest` aggregates."""

    async def list_active(
        self, *, limit: int = 100, offset: int = 0
    ) -> Sequence[AreaOfInterest]: ...
