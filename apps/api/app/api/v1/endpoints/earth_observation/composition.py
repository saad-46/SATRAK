"""Earth Observation API composition root.

Builds the container of repositories, storage, and read services the EO endpoints depend
on. The default binding uses the in-memory adapters (the shippable dev/test backend); when
the SQLAlchemy/PostGIS persistence adapter lands it is swapped here with zero endpoint
changes — the endpoints depend only on the repository ports.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.contexts.earth_observation.application.queries import SceneQueryService
from app.contexts.earth_observation.application.timeline.query_timeline import (
    RepositoryTimelineProvider,
)
from app.contexts.earth_observation.domain.aggregates.aoi import AreaOfInterest
from app.contexts.earth_observation.domain.aggregates.scene import Scene
from app.contexts.earth_observation.domain.ports.repositories import (
    AoiRepository,
    SceneRepository,
)
from app.contexts.earth_observation.infrastructure.persistence import (
    InMemoryAoiRepository,
    InMemorySceneRepository,
)
from app.contexts.earth_observation.infrastructure.storage.keying import StorageKeyStrategy
from app.shared.domain.scope import AccessScope
from app.shared.persistence.scoped import ScopedRepository
from app.shared.services.storage import InMemoryStorageProvider, StorageProvider


@dataclass
class EarthObservationApi:
    """Wired dependencies for the EO HTTP endpoints."""

    scenes: SceneRepository
    aois: AoiRepository
    storage: StorageProvider
    keys: StorageKeyStrategy
    scene_query: SceneQueryService
    timeline: RepositoryTimelineProvider

    # The raw repositories above are for trusted pipeline code and tests. Request handlers
    # reach tenant data only through these scope-bound views (enforced by an architecture test).
    def scoped_scenes(self, scope: AccessScope) -> ScopedRepository[Scene]:
        return ScopedRepository(self.scenes, scope)

    def scoped_aois(self, scope: AccessScope) -> ScopedRepository[AreaOfInterest]:
        return ScopedRepository(self.aois, scope)


def build_earth_observation_api() -> EarthObservationApi:
    """Assemble the EO API container with the in-memory persistence/storage backend."""
    scenes = InMemorySceneRepository()
    aois = InMemoryAoiRepository()
    return EarthObservationApi(
        scenes=scenes,
        aois=aois,
        storage=InMemoryStorageProvider(),
        keys=StorageKeyStrategy(),
        scene_query=SceneQueryService(scenes=scenes),
        timeline=RepositoryTimelineProvider(scenes=scenes),
    )
