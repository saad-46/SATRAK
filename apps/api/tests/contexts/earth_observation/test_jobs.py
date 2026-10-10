"""Story 16 — background processing: runner, tracker, retries, chaining, end-to-end."""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from app.contexts.earth_observation.application.acquisition.discover_scenes import (
    SceneDiscoveryService,
)
from app.contexts.earth_observation.application.ingestion.download_scene import (
    SceneDownloadService,
)
from app.contexts.earth_observation.application.ingestion.validate_scene import (
    ValidateSceneService,
    ValidationPolicy,
)
from app.contexts.earth_observation.application.jobs import (
    TASK_GENERATE_THUMBNAIL,
    TASK_GENERATE_TILES,
    TASK_INGEST_SCENE,
    TASK_PREPROCESS_SCENE,
    HandlerResult,
    InMemoryJobTracker,
    JobRecord,
    JobRunner,
    JobStatus,
    MissingPayloadField,
    ProgressReporter,
    UnknownJobError,
    UnknownTaskError,
    build_default_handlers,
    require_field,
)
from app.contexts.earth_observation.application.metadata.extract_metadata import (
    MetadataExtractionService,
)
from app.contexts.earth_observation.application.preprocessing.pipeline_spec import (
    PipelineSpec,
    PipelineStep,
)
from app.contexts.earth_observation.application.preprocessing.preprocess_scene import (
    PreprocessingService,
)
from app.contexts.earth_observation.application.preprocessing.thumbnails import (
    ThumbnailService,
    ThumbnailSpec,
)
from app.contexts.earth_observation.application.tiling.generate_tiles import (
    PyramidSpec,
    TilingService,
)
from app.contexts.earth_observation.domain.aggregates.scene import Scene
from app.contexts.earth_observation.domain.enums import SceneStatus
from app.contexts.earth_observation.domain.events import SceneAvailable
from app.contexts.earth_observation.domain.ports.metadata_extractor import ExtractedMetadata
from app.contexts.earth_observation.domain.value_objects import (
    CrsRef,
    TileCoord,
    TileMatrixSetRef,
)
from app.contexts.earth_observation.infrastructure.raster import InMemoryRaster, RasterGrid
from app.contexts.earth_observation.infrastructure.raster.encoding import RawFloat32Encoder
from app.contexts.earth_observation.infrastructure.storage.keying import StorageKeyStrategy
from app.shared.domain.errors import BusinessRuleViolation, ValueValidationError
from app.shared.domain.events import DomainEvent
from app.shared.domain.identifiers import new_id
from app.shared.events.bus import InMemoryEventBus
from app.shared.persistence.unit_of_work import InMemoryUnitOfWork
from app.shared.services.background_task import BackgroundTask, InlineTaskQueue
from app.shared.services.storage import InMemoryStorageProvider
from tests.contexts.earth_observation.fakes import (
    WINDOW,
    FakeProvider,
    InMemorySceneRepository,
    make_aoi,
    make_candidate,
)


async def _ok_handler(payload: Mapping[str, str], *, progress: ProgressReporter) -> HandlerResult:
    await progress(0.5)
    return HandlerResult(payload_update={"extra": "value"})


async def _halting_handler(
    payload: Mapping[str, str], *, progress: ProgressReporter
) -> HandlerResult:
    return HandlerResult(halt_chain=True)


async def _failing_handler(
    payload: Mapping[str, str], *, progress: ProgressReporter
) -> HandlerResult:
    raise RuntimeError("boom")


def _runner(
    queue: InlineTaskQueue, *, max_attempts: int = 3, chain: Mapping[str, str] | None = None
) -> tuple[JobRunner, InMemoryJobTracker]:
    tracker = InMemoryJobTracker()
    runner = JobRunner(tracker=tracker, queue=queue, max_attempts=max_attempts, chain=chain)
    return runner, tracker


# --- Runner: success, chaining, halting -------------------------------------------------
async def test_success_chains_next_stage_with_merged_payload() -> None:
    queue = InlineTaskQueue()
    runner, tracker = _runner(queue, chain={"stage.a": "stage.b"})
    runner.register("stage.a", _ok_handler)

    record = await runner.execute(BackgroundTask(name="stage.a", payload={"scene_id": "s-1"}))

    assert record.status is JobStatus.SUCCEEDED
    assert record.progress == 1.0
    assert [t.name for t in queue.enqueued] == ["stage.b"]
    assert queue.enqueued[0].payload == {"scene_id": "s-1", "extra": "value"}
    assert (await tracker.list_jobs())[0].task_name == "stage.a"


async def test_halt_chain_stops_pipeline() -> None:
    queue = InlineTaskQueue()
    runner, _ = _runner(queue, chain={"stage.a": "stage.b"})
    runner.register("stage.a", _halting_handler)
    record = await runner.execute(BackgroundTask(name="stage.a", payload={"scene_id": "s"}))
    assert record.status is JobStatus.SUCCEEDED
    assert queue.enqueued == []


async def test_end_of_chain_enqueues_nothing() -> None:
    queue = InlineTaskQueue()
    runner, _ = _runner(queue, chain={})
    runner.register("stage.z", _ok_handler)
    await runner.execute(BackgroundTask(name="stage.z", payload={"scene_id": "s"}))
    assert queue.enqueued == []


# --- Runner: retries and failure ----------------------------------------------------------
async def test_failure_retries_with_same_job_id_then_fails_permanently() -> None:
    queue = InlineTaskQueue()  # no handler registered -> enqueues are recorded only
    runner, _ = _runner(queue, max_attempts=3, chain={})
    runner.register("stage.flaky", _failing_handler)

    first = await runner.execute(BackgroundTask(name="stage.flaky", payload={"scene_id": "s"}))
    assert first.status is JobStatus.RETRYING
    assert first.error == "boom"
    retry_task = queue.enqueued[-1]
    assert retry_task.payload["attempt"] == "2"
    assert retry_task.payload["job_id"] == str(first.job_id)

    second = await runner.execute(retry_task)
    assert second.job_id == first.job_id  # same job tracked across attempts
    assert second.status is JobStatus.RETRYING
    assert second.attempt == 2

    final = await runner.execute(queue.enqueued[-1])
    assert final.status is JobStatus.FAILED
    assert final.attempt == 3
    assert len([t for t in queue.enqueued if t.name == "stage.flaky"]) == 2  # no 4th attempt


async def test_unknown_task_and_registration_guards() -> None:
    queue = InlineTaskQueue()
    runner, _ = _runner(queue)
    runner.register("stage.a", _ok_handler)
    with pytest.raises(BusinessRuleViolation):
        runner.register("stage.a", _ok_handler)
    with pytest.raises(UnknownTaskError):
        await runner.execute(BackgroundTask(name="stage.unknown"))
    with pytest.raises(BusinessRuleViolation):
        JobRunner(tracker=InMemoryJobTracker(), queue=queue, max_attempts=0)
    assert runner.task_names == ("stage.a",)


def test_require_field() -> None:
    assert require_field({"scene_id": "x"}, "scene_id") == "x"
    with pytest.raises(MissingPayloadField):
        require_field({}, "scene_id")
    with pytest.raises(MissingPayloadField):
        require_field({"scene_id": "  "}, "scene_id")


# --- Tracker and records ---------------------------------------------------------------------
async def test_tracker_lifecycle_and_status_reporting() -> None:
    tracker = InMemoryJobTracker()
    job_id = new_id()
    record = await tracker.start(
        job_id=job_id, task_name="t", payload={"scene_id": "s"}, attempt=1, max_attempts=3
    )
    assert record.status is JobStatus.RUNNING
    await tracker.report_progress(job_id, progress=0.4)
    assert (await tracker.get(job_id)).progress == 0.4  # type: ignore[union-attr]

    failed = await tracker.fail(job_id, error="e", will_retry=True)
    assert failed.status is JobStatus.RETRYING
    restarted = await tracker.start(
        job_id=job_id, task_name="t", payload={"scene_id": "s"}, attempt=2, max_attempts=3
    )
    assert restarted.attempt == 2
    assert restarted.progress == 0.0
    assert restarted.error is None

    done = await tracker.succeed(job_id)
    assert done.status is JobStatus.SUCCEEDED
    assert done.is_terminal is True
    assert len(await tracker.list_jobs()) == 1
    assert await tracker.get(new_id()) is None
    with pytest.raises(UnknownJobError):
        await tracker.succeed(new_id())
    with pytest.raises(ValueValidationError):
        await tracker.report_progress(job_id, progress=1.5)


def test_job_record_validation() -> None:
    with pytest.raises(ValueValidationError):
        JobRecord(job_id=new_id(), task_name="t", payload={}, attempt=0)
    with pytest.raises(ValueValidationError):
        JobRecord(job_id=new_id(), task_name="t", payload={}, progress=2.0)


# --- End-to-end: discovery through AVAILABLE via the task queue --------------------------------
async def test_full_pipeline_end_to_end_through_task_queue() -> None:
    bus = InMemoryEventBus()
    published: list[DomainEvent] = []
    bus.subscribe(DomainEvent, published.append)

    scenes = InMemorySceneRepository()
    storage = InMemoryStorageProvider()
    keys = StorageKeyStrategy()
    uow = InMemoryUnitOfWork(bus)
    provider = FakeProvider(candidates=[make_candidate()], chunks=[b"raster-bytes"])

    grid = RasterGrid(
        width=8,
        height=8,
        band_count=1,
        crs=CrsRef.wgs84(),
        origin_x=76.0,
        origin_y=14.0,
        pixel_size=0.25,
    )
    raster = InMemoryRaster(grid=grid, bands=[[float(v) for v in range(64)]])

    class _Loader:
        async def load(self, scene: Scene) -> InMemoryRaster:
            return raster

    class _Extractor:
        async def extract(self, *, source_uri: str) -> ExtractedMetadata:
            scene = await scenes.get_by_provider_scene_id(provider.candidates[0].provider_scene_id)
            assert scene is not None
            return ExtractedMetadata(acquisition=scene.acquisition, crs=CrsRef(epsg=32643))

    thumbnails = ThumbnailService(
        storage=storage,
        keys=keys,
        encoder=RawFloat32Encoder(),
        specs=(
            ThumbnailSpec(variant="quicklook", max_dimension=4),
            ThumbnailSpec(variant="preview", max_dimension=2),
        ),
    )
    handlers = build_default_handlers(
        download=SceneDownloadService(
            provider=provider, scenes=scenes, storage=storage, keys=keys, uow=uow
        ),
        validation=ValidateSceneService(
            scenes=scenes, uow=uow, policy=ValidationPolicy(expected_provider="sentinel-2")
        ),
        metadata=MetadataExtractionService(extractor=_Extractor(), scenes=scenes, uow=uow),
        preprocessing=PreprocessingService(
            scenes=scenes,
            uow=uow,
            spec=PipelineSpec(
                version="1.0.0", steps=(PipelineStep.NORMALIZE, PipelineStep.THUMBNAIL)
            ),
            loader=_Loader(),
            thumbnailer=thumbnails,
        ),
        tiling=TilingService(
            scenes=scenes,
            uow=uow,
            loader=_Loader(),
            storage=storage,
            keys=keys,
            encoder=RawFloat32Encoder(),
            pyramid=PyramidSpec(min_zoom=1, max_zoom=2, tile_size=4),
        ),
        thumbnails=thumbnails,
        scenes=scenes,
        loader=_Loader(),
    )

    queue = InlineTaskQueue()
    tracker = InMemoryJobTracker()
    runner = JobRunner(tracker=tracker, queue=queue)
    for name, handler in handlers.items():
        runner.register(name, handler)
    for name in runner.task_names:
        queue.register(name, runner.execute)

    # Discovery enqueues ingest; the inline queue then drives the whole chain.
    discovery = SceneDiscoveryService(provider=provider, scenes=scenes, uow=uow, task_queue=queue)
    result = await discovery.discover(aoi=make_aoi(), window=WINDOW)
    assert result.created == 1

    scene = await scenes.require(result.scene_ids[0])
    assert scene.status is SceneStatus.AVAILABLE
    assert scene.crs == CrsRef(epsg=32643)
    assert any(isinstance(e, SceneAvailable) for e in published)

    # Raw asset + 2 thumbnails + 2 tiles all stored under their deterministic keys.
    assert await storage.exists(f"thumbnails/{scene.id}/quicklook.bin")
    assert await storage.exists(f"thumbnails/{scene.id}/preview.bin")
    assert await storage.exists(
        keys.tile_key(
            tile_matrix_set=TileMatrixSetRef.web_mercator_quad(),
            scene_id=scene.id,
            pipeline_version="1.0.0",
            tile=TileCoord(z=1, x=1, y=0),
            extension="bin",
        )
    )
    assert await storage.exists(
        keys.tile_key(
            tile_matrix_set=TileMatrixSetRef.web_mercator_quad(),
            scene_id=scene.id,
            pipeline_version="1.0.0",
            tile=TileCoord(z=2, x=2, y=1),
            extension="bin",
        )
    )
    assert scene.checksum_sha256 is not None

    tracker_jobs = await tracker.list_jobs()
    assert len(tracker_jobs) == 5
    assert all(job.status is JobStatus.SUCCEEDED for job in tracker_jobs)
    assert {job.task_name for job in tracker_jobs} == {
        TASK_INGEST_SCENE,
        "earth_observation.validate_scene",
        "earth_observation.extract_metadata",
        TASK_PREPROCESS_SCENE,
        TASK_GENERATE_TILES,
    }

    # Standalone thumbnail re-generation runs outside the chain.
    regen = await runner.execute(
        BackgroundTask(name=TASK_GENERATE_THUMBNAIL, payload={"scene_id": str(scene.id)})
    )
    assert regen.status is JobStatus.SUCCEEDED
    assert len(await tracker.list_jobs()) == 6
