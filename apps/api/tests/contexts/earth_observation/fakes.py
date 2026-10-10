"""Shared in-memory fakes for Earth Observation application-service tests."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from uuid import UUID

from app.contexts.earth_observation.domain.aggregates.aoi import AreaOfInterest
from app.contexts.earth_observation.domain.aggregates.scene import Scene
from app.contexts.earth_observation.domain.enums import SensorType
from app.contexts.earth_observation.domain.ports.imagery_provider import SceneCandidate
from app.contexts.earth_observation.domain.value_objects import (
    AcquisitionMetadata,
    CloudCoverPercentage,
    ProviderCapabilities,
    ProviderSceneId,
)
from app.contexts.earth_observation.infrastructure.persistence import (
    InMemoryAoiRepository,
    InMemorySceneRepository,
)
from app.shared.value_objects.geo import BoundingBox
from app.shared.value_objects.ranges import TimeRange

__all__ = [
    "ACQUIRED_AT",
    "BBOX",
    "WINDOW",
    "FakeProvider",
    "InMemoryAoiRepository",
    "InMemorySceneRepository",
    "make_aoi",
    "make_candidate",
    "make_scene",
]

BBOX = BoundingBox(min_longitude=76.0, min_latitude=12.0, max_longitude=78.0, max_latitude=14.0)
ACQUIRED_AT = datetime(2024, 6, 1, 5, 32, tzinfo=UTC)
JURISDICTION = UUID("00000000-0000-4000-8000-0000000000a1")
WINDOW = TimeRange(start=datetime(2024, 1, 1, tzinfo=UTC), end=datetime(2024, 12, 31, tzinfo=UTC))


def make_candidate(
    native_id: str = "S2A_1",
    *,
    provider: str = "sentinel-2",
    bbox: BoundingBox = BBOX,
    cloud_pct: float | None = 5.0,
) -> SceneCandidate:
    return SceneCandidate(
        provider_scene_id=ProviderSceneId(provider=provider, native_id=native_id),
        bounding_box=bbox,
        acquisition=AcquisitionMetadata(
            acquired_at=ACQUIRED_AT,
            sensor_type=SensorType.OPTICAL,
            cloud_cover=CloudCoverPercentage(value=cloud_pct) if cloud_pct is not None else None,
        ),
    )


def make_scene(native_id: str = "S2A_1", *, cloud_pct: float | None = 5.0) -> Scene:
    candidate = make_candidate(native_id, cloud_pct=cloud_pct)
    return Scene.create(
        provider_scene_id=candidate.provider_scene_id,
        bounding_box=candidate.bounding_box,
        acquisition=candidate.acquisition,
        jurisdiction_id=JURISDICTION,
    )


def make_aoi(name: str = "Ward 12", *, bbox: BoundingBox = BBOX) -> AreaOfInterest:
    return AreaOfInterest.create(name=name, bounding_box=bbox, jurisdiction_id=JURISDICTION)


class FakeProvider:
    """Serves preset candidates and byte chunks through the domain provider port."""

    def __init__(
        self,
        *,
        candidates: Sequence[SceneCandidate] = (),
        chunks: Sequence[bytes] = (b"pixel-data",),
    ) -> None:
        self.candidates = list(candidates)
        self.chunks = list(chunks)
        self.fetched: list[ProviderSceneId] = []

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider="fake", sensor_types=frozenset({SensorType.OPTICAL}), min_gsd_m=10.0
        )

    async def search(self, *, area: BoundingBox, window: TimeRange) -> Sequence[SceneCandidate]:
        return tuple(self.candidates)

    def fetch(self, provider_scene_id: ProviderSceneId) -> AsyncIterator[bytes]:
        self.fetched.append(provider_scene_id)

        async def _gen() -> AsyncIterator[bytes]:
            for chunk in self.chunks:
                yield chunk

        return _gen()
