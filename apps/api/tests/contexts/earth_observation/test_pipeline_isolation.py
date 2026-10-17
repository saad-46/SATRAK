"""Pipeline isolation: stage services act for one jurisdiction and cannot cross into another.

Trust boundary (ADR-0011): a task payload may *narrow* work to one jurisdiction; it can never
widen it. Every stage fails closed on a missing scope, a malformed scope, or a record that
belongs to a different jurisdiction, and a violation is never retried.
"""

from __future__ import annotations

import ast
import pathlib
import uuid
from collections.abc import Callable, Coroutine
from typing import Any

import pytest

from app.contexts.earth_observation.application.acquisition.discover_scenes import (
    SceneDiscoveryService,
)
from app.contexts.earth_observation.application.ingestion.download_scene import (
    SceneDownloadService,
)
from app.contexts.earth_observation.application.ingestion.validate_scene import (
    ValidateSceneService,
)
from app.contexts.earth_observation.application.jobs import (
    InMemoryJobTracker,
    JobRunner,
    JobStatus,
    build_default_handlers,
)
from app.contexts.earth_observation.application.jobs.runner import (
    TASK_GENERATE_THUMBNAIL,
    TASK_INGEST_SCENE,
    scope_from_payload,
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
from app.contexts.earth_observation.domain.ports.metadata_extractor import ExtractedMetadata
from app.contexts.earth_observation.domain.value_objects import CrsRef
from app.contexts.earth_observation.infrastructure.persistence import InMemorySceneRepository
from app.contexts.earth_observation.infrastructure.raster import InMemoryRaster, RasterGrid
from app.contexts.earth_observation.infrastructure.raster.encoding import RawFloat32Encoder
from app.contexts.earth_observation.infrastructure.storage.keying import StorageKeyStrategy
from app.shared.domain.errors import BusinessRuleViolation
from app.shared.domain.scope import OutOfScopeError, TenantScope
from app.shared.events.bus import InMemoryEventBus
from app.shared.persistence.unit_of_work import InMemoryUnitOfWork
from app.shared.services.background_task import BackgroundTask, InlineTaskQueue
from app.shared.services.storage import InMemoryStorageProvider
from tests.contexts.earth_observation.fakes import (
    JURISDICTION,
    SCOPE,
    WINDOW,
    FakeProvider,
    make_aoi,
    make_candidate,
    make_scene,
)

OTHER = uuid.UUID("00000000-0000-4000-8000-0000000000b2")
OTHER_SCOPE = TenantScope(frozenset({OTHER}))


class _Loader:
    async def load(self, scene: Scene) -> InMemoryRaster:
        grid = RasterGrid(
            width=4,
            height=4,
            band_count=1,
            crs=CrsRef.wgs84(),
            origin_x=76.0,
            origin_y=14.0,
            pixel_size=0.5,
        )
        return InMemoryRaster(grid=grid, bands=[[float(v) for v in range(16)]])


class _Extractor:
    async def extract(self, *, source_uri: str) -> ExtractedMetadata:  # pragma: no cover
        raise AssertionError("an out-of-scope scene must never reach the extractor")


class Pipeline:
    def __init__(self) -> None:
        self.scenes = InMemorySceneRepository()
        self.storage = InMemoryStorageProvider()
        self.keys = StorageKeyStrategy()
        self.uow = InMemoryUnitOfWork(InMemoryEventBus())
        self.provider = FakeProvider(candidates=[make_candidate()], chunks=[b"raster-bytes"])
        thumbnails = ThumbnailService(
            storage=self.storage,
            keys=self.keys,
            encoder=RawFloat32Encoder(),
            specs=(ThumbnailSpec(variant="quicklook", max_dimension=2),),
        )
        self.download = SceneDownloadService(
            provider=self.provider,
            scenes=self.scenes,
            storage=self.storage,
            keys=self.keys,
            uow=self.uow,
        )
        self.validation = ValidateSceneService(scenes=self.scenes, uow=self.uow)
        self.metadata = MetadataExtractionService(
            extractor=_Extractor(), scenes=self.scenes, uow=self.uow
        )
        self.preprocessing = PreprocessingService(
            scenes=self.scenes,
            uow=self.uow,
            spec=PipelineSpec(version="1.0.0", steps=(PipelineStep.NORMALIZE,)),
            loader=_Loader(),
            thumbnailer=thumbnails,
        )
        self.tiling = TilingService(
            scenes=self.scenes,
            uow=self.uow,
            loader=_Loader(),
            storage=self.storage,
            keys=self.keys,
            encoder=RawFloat32Encoder(),
            pyramid=PyramidSpec(min_zoom=1, max_zoom=1, tile_size=4),
        )
        self.queue = InlineTaskQueue()
        self.tracker = InMemoryJobTracker()
        self.runner = JobRunner(tracker=self.tracker, queue=self.queue)
        handlers = build_default_handlers(
            download=self.download,
            validation=self.validation,
            metadata=self.metadata,
            preprocessing=self.preprocessing,
            tiling=self.tiling,
            thumbnails=thumbnails,
            scenes=self.scenes,
            loader=_Loader(),
        )
        for name, handler in handlers.items():
            self.runner.register(name, handler)
        for name in self.runner.task_names:
            self.queue.register(name, self.runner.execute)


@pytest.fixture
def pipeline() -> Pipeline:
    return Pipeline()


async def _foreign_scene(pipeline: Pipeline) -> Scene:
    scene = make_scene("FOREIGN")
    scene.jurisdiction_id = OTHER  # held by another jurisdiction
    await pipeline.scenes.add(scene)
    return scene


Stage = Callable[[Pipeline, Scene, TenantScope], Coroutine[Any, Any, object]]
STAGES: dict[str, Stage] = {
    "download": lambda p, s, scope: p.download.download(scene_id=s.id, scope=scope),
    "validate": lambda p, s, scope: p.validation.validate(scene_id=s.id, scope=scope),
    "extract": lambda p, s, scope: p.metadata.extract_and_register(
        scene_id=s.id, source_uri="raw/x", scope=scope
    ),
    "preprocess": lambda p, s, scope: p.preprocessing.preprocess(scene_id=s.id, scope=scope),
    "tiles": lambda p, s, scope: p.tiling.generate(scene_id=s.id, scope=scope),
}


@pytest.mark.parametrize("stage", sorted(STAGES))
async def test_a_stage_refuses_a_scene_of_another_jurisdiction(
    pipeline: Pipeline, stage: str
) -> None:
    scene = await _foreign_scene(pipeline)
    before = (scene.status, scene.version)
    with pytest.raises(OutOfScopeError):
        await STAGES[stage](pipeline, scene, SCOPE)
    assert (scene.status, scene.version) == before  # nothing was read into a change
    assert pipeline.storage._objects == {}  # type: ignore[attr-defined]  # nothing was written


@pytest.mark.parametrize("stage", sorted(STAGES))
async def test_a_stage_without_a_scope_cannot_be_called(pipeline: Pipeline, stage: str) -> None:
    scene = make_scene("OWN")
    await pipeline.scenes.add(scene)
    call = STAGES[stage]
    with pytest.raises(TypeError):
        await call(pipeline, scene, None)  # type: ignore[arg-type]  # not an AccessScope
    service_call = {
        "download": lambda: pipeline.download.download(scene_id=scene.id),  # type: ignore[call-arg]
        "validate": lambda: pipeline.validation.validate(scene_id=scene.id),  # type: ignore[call-arg]
        "extract": lambda: pipeline.metadata.extract_and_register(  # type: ignore[call-arg]
            scene_id=scene.id, source_uri="raw/x"
        ),
        "preprocess": lambda: pipeline.preprocessing.preprocess(scene_id=scene.id),  # type: ignore[call-arg]
        "tiles": lambda: pipeline.tiling.generate(scene_id=scene.id),  # type: ignore[call-arg]
    }[stage]
    with pytest.raises(TypeError):
        await service_call()


# --- Task payloads -----------------------------------------------------------------------------
def _task(name: str, scene: Scene, **payload: str) -> BackgroundTask:
    return BackgroundTask(name=name, payload={"scene_id": str(scene.id), **payload})


async def test_a_task_naming_another_jurisdictions_scene_fails_once_and_changes_nothing(
    pipeline: Pipeline,
) -> None:
    scene = await _foreign_scene(pipeline)
    record = await pipeline.runner.execute(
        _task(TASK_INGEST_SCENE, scene, jurisdiction_id=str(JURISDICTION))
    )
    assert record.status is JobStatus.FAILED
    assert record.attempt == 1  # a violation is not retried
    assert pipeline.queue.enqueued == []  # and the pipeline does not continue
    assert scene.checksum_sha256 is None
    assert pipeline.provider.fetched == []  # the provider was never asked for foreign data


async def test_a_task_for_the_right_jurisdiction_is_processed(pipeline: Pipeline) -> None:
    scene = make_scene("OWN")
    await pipeline.scenes.add(scene)
    record = await pipeline.runner.execute(
        _task(TASK_INGEST_SCENE, scene, jurisdiction_id=str(JURISDICTION))
    )
    assert record.status is JobStatus.SUCCEEDED
    assert scene.checksum_sha256 is not None
    assert pipeline.queue.enqueued[0].payload["jurisdiction_id"] == str(JURISDICTION)


@pytest.mark.parametrize(
    "bad",
    [None, "", "   ", "*", "all", "system", "not-a-uuid"],
    ids=["missing", "empty", "blank", "wildcard", "all", "system", "malformed"],
)
async def test_a_task_without_a_usable_jurisdiction_is_refused(
    pipeline: Pipeline, bad: str | None
) -> None:
    scene = make_scene("OWN")
    await pipeline.scenes.add(scene)
    extra = {} if bad is None else {"jurisdiction_id": bad}
    record = await pipeline.runner.execute(_task(TASK_GENERATE_THUMBNAIL, scene, **extra))
    assert record.status in {JobStatus.FAILED, JobStatus.RETRYING}
    assert pipeline.provider.fetched == [] and scene.checksum_sha256 is None
    with pytest.raises(BusinessRuleViolation):
        scope_from_payload({"scene_id": "x", **extra})


def test_a_payload_can_only_name_one_tenant_never_the_system_scope() -> None:
    scope = scope_from_payload({"jurisdiction_id": str(OTHER)})
    assert isinstance(scope, TenantScope) and scope.allows(OTHER) and not scope.allows(JURISDICTION)


async def test_standalone_thumbnail_task_is_bound_to_the_payload_jurisdiction(
    pipeline: Pipeline,
) -> None:
    scene = await _foreign_scene(pipeline)
    record = await pipeline.runner.execute(
        _task(TASK_GENERATE_THUMBNAIL, scene, jurisdiction_id=str(JURISDICTION))
    )
    assert record.status is JobStatus.FAILED and record.attempt == 1
    assert pipeline.storage._objects == {}  # type: ignore[attr-defined]


# --- Discovery ---------------------------------------------------------------------------------
async def test_discovery_is_per_jurisdiction_and_does_not_reveal_another_tenants_scene(
    pipeline: Pipeline,
) -> None:
    # The other jurisdiction already holds this provider scene: a global lookup would call it
    # a duplicate for ours.
    candidate = make_candidate("DUP")
    held = Scene.create(
        provider_scene_id=candidate.provider_scene_id,
        bounding_box=candidate.bounding_box,
        acquisition=candidate.acquisition,
        jurisdiction_id=OTHER,
    )
    await pipeline.scenes.add(held)
    pipeline.provider.candidates = [candidate]

    service = SceneDiscoveryService(
        provider=pipeline.provider,
        scenes=pipeline.scenes,
        uow=pipeline.uow,
        task_queue=pipeline.queue,
    )
    result = await service.discover(aoi=make_aoi(), window=WINDOW)

    assert result.duplicates == 0 and result.created == 1  # the other tenant's row is invisible
    created = await pipeline.scenes.require(result.scene_ids[0])
    assert created.jurisdiction_id == JURISDICTION and created.id != held.id
    assert held.jurisdiction_id == OTHER  # untouched
    assert (
        await pipeline.scenes.get_by_provider_scene_id(
            candidate.provider_scene_id, scope=OTHER_SCOPE
        )
        is held
    )


async def test_provider_scene_lookup_requires_a_scope(pipeline: Pipeline) -> None:
    candidate = make_candidate()
    with pytest.raises(TypeError):
        await pipeline.scenes.get_by_provider_scene_id(candidate.provider_scene_id)  # type: ignore[call-arg]


# --- Architecture guard ------------------------------------------------------------------------
def test_pipeline_code_never_calls_unscoped_repository_methods() -> None:
    """Application code reaches scenes only through ScopedRepository or scope-taking methods."""
    unscoped = {"get", "require", "add", "update", "delete", "list", "exists", "count"}
    root = pathlib.Path(__file__).resolve().parents[3] / "app" / "contexts" / "earth_observation"
    offenders: list[str] = []
    for path in (root / "application").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if (
                isinstance(node, ast.Attribute)
                and node.attr in unscoped
                and isinstance(node.value, ast.Attribute)
                and node.value.attr in {"_scenes", "_aois", "scenes", "aois"}
            ):
                offenders.append(f"{path.name}:{node.lineno} .{node.value.attr}.{node.attr}")
    assert offenders == []
