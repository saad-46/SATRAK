"""Story 10 — scene discovery orchestration and streamed download."""

from __future__ import annotations

import hashlib

import pytest

from app.contexts.earth_observation.application.acquisition.discover_scenes import (
    INGEST_SCENE_TASK,
    DiscoveryFilter,
    SceneDiscoveryService,
)
from app.contexts.earth_observation.application.ingestion.download_scene import (
    EmptyDownloadError,
    SceneDownloadService,
)
from app.contexts.earth_observation.domain.enums import SceneStatus
from app.contexts.earth_observation.domain.events import (
    ImageDiscovered,
    ImageDownloaded,
    ImageRejected,
)
from app.contexts.earth_observation.infrastructure.storage.keying import StorageKeyStrategy
from app.shared.domain.events import DomainEvent
from app.shared.events.bus import InMemoryEventBus
from app.shared.persistence.unit_of_work import InMemoryUnitOfWork
from app.shared.services.background_task import InlineTaskQueue
from app.shared.services.storage import InMemoryStorageProvider
from tests.contexts.earth_observation.fakes import (
    BBOX,
    WINDOW,
    FakeProvider,
    InMemorySceneRepository,
    make_aoi,
    make_candidate,
    make_scene,
)


def _bus_with_log() -> tuple[InMemoryEventBus, list[DomainEvent]]:
    bus = InMemoryEventBus()
    published: list[DomainEvent] = []
    bus.subscribe(DomainEvent, published.append)
    return bus, published


# --- Discovery -------------------------------------------------------------------
async def test_discovery_registers_filters_and_dedups() -> None:
    bus, published = _bus_with_log()
    scenes = InMemorySceneRepository()
    queue = InlineTaskQueue()
    aoi = make_aoi()

    far_bbox = type(BBOX)(
        min_longitude=100.0, min_latitude=40.0, max_longitude=101.0, max_latitude=41.0
    )
    provider = FakeProvider(
        candidates=[
            make_candidate("keep-1", cloud_pct=5.0),
            make_candidate("cloudy", cloud_pct=80.0),  # filtered: cloud
            make_candidate("offsite", bbox=far_bbox),  # filtered: no AOI overlap
            make_candidate("keep-1", cloud_pct=5.0),  # duplicate within the same pass
        ]
    )
    service = SceneDiscoveryService(
        provider=provider,
        scenes=scenes,
        uow=InMemoryUnitOfWork(bus),
        task_queue=queue,
        discovery_filter=DiscoveryFilter(max_cloud_cover_pct=20.0),
    )

    result = await service.discover(aoi=aoi, window=WINDOW)

    assert result.created == 1
    assert result.filtered_out == 2
    assert result.duplicates == 1
    stored = await scenes.get(result.scene_ids[0])
    assert stored is not None
    assert stored.status is SceneStatus.DISCOVERED
    assert aoi.id in stored.aoi_ids
    assert sum(isinstance(e, ImageDiscovered) for e in published) == 1
    assert [t.name for t in queue.enqueued] == [INGEST_SCENE_TASK]
    assert queue.enqueued[0].payload == {"scene_id": str(stored.id)}


async def test_discovery_skips_scenes_already_registered() -> None:
    scenes = InMemorySceneRepository()
    existing = make_scene("known")
    existing.pull_events()
    await scenes.add(existing)

    service = SceneDiscoveryService(
        provider=FakeProvider(candidates=[make_candidate("known")]),
        scenes=scenes,
        uow=InMemoryUnitOfWork(),
    )
    result = await service.discover(aoi=make_aoi(), window=WINDOW)
    assert result.created == 0
    assert result.duplicates == 1
    assert await scenes.count() == 1


async def test_discovery_without_task_queue_still_registers() -> None:
    scenes = InMemorySceneRepository()
    service = SceneDiscoveryService(
        provider=FakeProvider(candidates=[make_candidate()]),
        scenes=scenes,
        uow=InMemoryUnitOfWork(),
    )
    result = await service.discover(aoi=make_aoi(), window=WINDOW)
    assert result.created == 1


def test_discovery_filter_accepts_unknown_cloud() -> None:
    aoi = make_aoi()
    candidate = make_candidate("no-cloud-info", cloud_pct=None)
    assert DiscoveryFilter(max_cloud_cover_pct=10.0).accepts(candidate, aoi=aoi) is True


# --- Download ---------------------------------------------------------------------
async def test_download_streams_hashes_and_stores() -> None:
    bus, published = _bus_with_log()
    scenes = InMemorySceneRepository()
    scene = make_scene()
    scene.pull_events()
    await scenes.add(scene)

    chunks = [b"chunk-a", b"chunk-b", b""]
    provider = FakeProvider(chunks=chunks)
    storage = InMemoryStorageProvider()
    service = SceneDownloadService(
        provider=provider,
        scenes=scenes,
        storage=storage,
        keys=StorageKeyStrategy(),
        uow=InMemoryUnitOfWork(bus),
    )

    reference = await service.download(scene_id=scene.id)

    expected_checksum = hashlib.sha256(b"chunk-achunk-b").hexdigest()
    assert scene.status is SceneStatus.DOWNLOADED
    assert scene.checksum_sha256 == expected_checksum
    assert reference.checksum_sha256 == expected_checksum
    assert expected_checksum in reference.storage_key
    assert reference.storage_key.startswith("raw/sentinel-2/optical/2024/06/01/")
    stored = await storage.open(reference.storage_key)
    assert stored.data == b"chunk-achunk-b"
    assert any(isinstance(e, ImageDownloaded) for e in published)


async def test_download_empty_stream_rejects_scene() -> None:
    bus, published = _bus_with_log()
    scenes = InMemorySceneRepository()
    scene = make_scene()
    scene.pull_events()
    await scenes.add(scene)

    service = SceneDownloadService(
        provider=FakeProvider(chunks=[]),
        scenes=scenes,
        storage=InMemoryStorageProvider(),
        keys=StorageKeyStrategy(),
        uow=InMemoryUnitOfWork(bus),
    )

    with pytest.raises(EmptyDownloadError):
        await service.download(scene_id=scene.id)
    assert scene.status is SceneStatus.REJECTED
    assert any(isinstance(e, ImageRejected) for e in published)
