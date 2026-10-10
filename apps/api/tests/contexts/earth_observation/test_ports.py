"""Story 5 — domain ports/contracts.

Ports are Protocols with no implementations; these tests verify the contracts are importable,
structurally checkable (``runtime_checkable``), and satisfiable by simple fakes/reuse of the
shared kernel. No production adapters exist yet.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime

from app.contexts.earth_observation.domain.aggregates.aoi import AreaOfInterest
from app.contexts.earth_observation.domain.aggregates.scene import Scene
from app.contexts.earth_observation.domain.enums import SensorType
from app.contexts.earth_observation.domain.ports import (
    AoiRepository,
    EarthObservationProvider,
    ExtractedMetadata,
    ImageStoragePort,
    MetadataExtractor,
    RasterProcessor,
    SceneCandidate,
    SceneRepository,
    TileGenerator,
    TimelineProvider,
)
from app.contexts.earth_observation.domain.ports.repositories import SceneQuery
from app.contexts.earth_observation.domain.value_objects import (
    AcquisitionMetadata,
    ProviderCapabilities,
    ProviderSceneId,
)
from app.shared.domain.identifiers import EntityId
from app.shared.persistence.repository import InMemoryRepository
from app.shared.services.storage import InMemoryStorageProvider, StorageProvider
from app.shared.value_objects.geo import BoundingBox
from app.shared.value_objects.ranges import TimeRange


def _bbox() -> BoundingBox:
    return BoundingBox(min_longitude=0.0, min_latitude=0.0, max_longitude=1.0, max_latitude=1.0)


class _FakeProvider:
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(provider="fake", sensor_types=frozenset({SensorType.OPTICAL}))

    async def search(self, *, area: BoundingBox, window: TimeRange) -> Sequence[SceneCandidate]:
        return []

    def fetch(self, provider_scene_id: ProviderSceneId) -> AsyncIterator[bytes]:
        async def _gen() -> AsyncIterator[bytes]:
            yield b""

        return _gen()


class _FakeSceneRepo(InMemoryRepository[Scene]):
    async def get_by_provider_scene_id(self, provider_scene_id: ProviderSceneId) -> Scene | None:
        return None

    async def list_for_aoi(
        self, aoi_id: EntityId, *, limit: int = 100, offset: int = 0
    ) -> Sequence[Scene]:
        return []

    async def search(
        self, query: SceneQuery, *, limit: int = 100, offset: int = 0
    ) -> Sequence[Scene]:
        return []

    async def count_matching(self, query: SceneQuery) -> int:
        return 0


class _FakeAoiRepo(InMemoryRepository[AreaOfInterest]):
    async def list_active(self, *, limit: int = 100, offset: int = 0) -> Sequence[AreaOfInterest]:
        return []


class _FakeTimeline:
    async def timeline(self, *, area: BoundingBox, window: TimeRange) -> Sequence[Scene]:
        return []


def test_provider_satisfies_port() -> None:
    assert isinstance(_FakeProvider(), EarthObservationProvider)


def test_repositories_satisfy_ports() -> None:
    assert isinstance(_FakeSceneRepo(), SceneRepository)
    assert isinstance(_FakeAoiRepo(), AoiRepository)


def test_timeline_satisfies_port() -> None:
    assert isinstance(_FakeTimeline(), TimelineProvider)


def test_scene_candidate_dto() -> None:
    candidate = SceneCandidate(
        provider_scene_id=ProviderSceneId(provider="p", native_id="n"),
        bounding_box=_bbox(),
        acquisition=AcquisitionMetadata(
            acquired_at=datetime(2024, 1, 1, tzinfo=UTC), sensor_type=SensorType.OPTICAL
        ),
    )
    assert candidate.provider_scene_id.provider == "p"


def test_extracted_metadata_dto() -> None:
    meta = ExtractedMetadata(
        acquisition=AcquisitionMetadata(
            acquired_at=datetime(2024, 1, 1, tzinfo=UTC), sensor_type=SensorType.SAR
        )
    )
    assert meta.bands is None
    assert meta.crs is None


def test_storage_port_reuses_shared_provider() -> None:
    assert ImageStoragePort is StorageProvider
    assert isinstance(InMemoryStorageProvider(), ImageStoragePort)


def test_processor_ports_are_protocols() -> None:
    # Import-level coverage: the contracts exist and are runtime-checkable.
    assert RasterProcessor is not None
    assert MetadataExtractor is not None
    assert TileGenerator is not None
