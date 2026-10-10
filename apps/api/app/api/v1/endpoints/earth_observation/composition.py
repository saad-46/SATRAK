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
from app.contexts.earth_observation.domain.ports.repositories import (
    AoiRepository,
    SceneRepository,
)
from app.contexts.earth_observation.infrastructure.persistence import (
    InMemoryAoiRepository,
    InMemorySceneRepository,
)
from app.contexts.earth_observation.infrastructure.storage.keying import StorageKeyStrategy
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
